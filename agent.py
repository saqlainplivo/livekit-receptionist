"""
LiveKit AI Receptionist with Groq LLM

Stack:
- LLM:  Groq (Llama 3.3 70B) via OpenAI-compatible API
- STT:  Deepgram Nova-2
- TTS:  Deepgram Aura (asteria voice)
- VAD:  Silero
- Turn: LiveKit turn-detector plugin
"""

import os
import time
import json
from typing import Annotated

from dotenv import load_dotenv
from loguru import logger
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, groq, silero

from db import init_db, log_call

load_dotenv()

# ── System prompt ──────────────────────────────────────────────────────────────

RECEPTIONIST_INSTRUCTIONS = """You are an AI receptionist for TechCorp Solutions. Keep responses brief and conversational.
Your output will be converted to audio, so avoid special characters, markdown, or formatting.
Speak naturally as if you're on a phone call.

Your responsibilities:
1. Greet callers warmly
2. Determine their intent: sales inquiry, technical support, or general FAQ
3. Use the provided tools to answer questions about business hours, location, and FAQs
4. For sales inquiries, gather their name and interest, then let them know a sales rep will follow up
5. For technical support, gather a brief description of their issue and let them know a technician will call back
6. Always be polite, professional, and helpful
"""

# ── Tool functions ─────────────────────────────────────────────────────────────

class ReceptionistFunctions(llm.FunctionContext):
    def __init__(self, caller_number: str) -> None:
        super().__init__()
        self._caller_number = caller_number
        self._detected_intent = "unknown"
        self._start_time = time.time()

    @llm.ai_callable(description="Get the current business hours for TechCorp Solutions.")
    def get_business_hours(self) -> str:
        logger.info("Tool called: get_business_hours")
        return (
            "TechCorp Solutions is open Monday through Friday, 9 AM to 6 PM Eastern Time. "
            "We are closed on weekends and major holidays."
        )

    @llm.ai_callable(description="Get the office location and address for TechCorp Solutions.")
    def get_office_location(self) -> str:
        logger.info("Tool called: get_office_location")
        return (
            "TechCorp Solutions is located at 123 Innovation Drive, Suite 400, "
            "San Francisco, California 94105."
        )

    @llm.ai_callable(description="Log the detected caller intent for call tracking purposes.")
    def log_caller_intent(
        self,
        intent: Annotated[str, llm.TypeInfo(description="The detected intent category: sales, support, faq, or other")],
        summary: Annotated[str, llm.TypeInfo(description="A brief summary of what the caller needs")],
    ) -> str:
        logger.info(f"Tool called: log_caller_intent(intent={intent}, summary={summary})")
        self._detected_intent = intent
        return f"Intent recorded as: {intent}."

# ── Post-call analysis ─────────────────────────────────────────────────────────

async def perform_post_call_analysis(agent: VoicePipelineAgent):
    """Use the Groq LLM to summarize the finished call."""
    if not agent.chat_ctx.messages:
        return "No summary", "unknown"

    try:
        analysis_ctx = agent.chat_ctx.copy()
        analysis_ctx.append(
            role="system",
            text=(
                'Analyze this conversation. Respond ONLY with JSON: '
                '{"summary": "<1-sentence summary>", "intent": "<sales|support|hours|location|other>"}'
            ),
        )

        response = await agent.llm.chat(chat_ctx=analysis_ctx)

        full_text = ""
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                full_text += content

        # Extract JSON even if wrapped in markdown fences
        if "```json" in full_text:
            full_text = full_text.split("```json")[1].split("```")[0].strip()
        elif "```" in full_text:
            full_text = full_text.split("```")[1].split("```")[0].strip()

        analysis = json.loads(full_text)
        return analysis.get("summary", "No summary"), analysis.get("intent", "unknown")
    except Exception as e:
        logger.error(f"Post-call analysis failed: {e}")
        return "Analysis failed", "error"

# ── Agent entrypoint ───────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    caller_number = (
        participant.identity
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        else "browser-user"
    )
    logger.info(f"Starting session for {caller_number}")

    fnc_ctx = ReceptionistFunctions(caller_number)

    # ── Groq LLM ─────────────────────────────────────────────────────────
    llm_service = groq.LLM(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
    )

    # ── Voice pipeline ────────────────────────────────────────────────────
    agent = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-2",
            interim_results=True,
            endpointing_ms=300,
        ),
        llm=llm_service,
        tts=deepgram.TTS(voice="aura-asteria-en"),
        chat_ctx=llm.ChatContext().append(
            role="system",
            text=RECEPTIONIST_INSTRUCTIONS,
        ),
        fnc_ctx=fnc_ctx,
    )

    agent.start(ctx.room, participant)

    # Immediate greeting so the caller hears something right away
    await agent.say(
        "Hello! Thank you for calling TechCorp Solutions. "
        "My name is Rachel, your virtual receptionist. How can I help you today?",
        allow_interruptions=True,
    )

    # ── On call end: analyze & log ────────────────────────────────────────
    @ctx.add_on_finished
    async def on_finished():
        duration = int(time.time() - fnc_ctx._start_time)

        summary, intent = await perform_post_call_analysis(agent)

        transcript = ""
        for msg in agent.chat_ctx.messages:
            if msg.role == "user" and msg.text:
                transcript += f"Caller: {msg.text} | "
            elif msg.role == "assistant" and msg.text:
                transcript += f"Bot: {msg.text} | "

        log_call(
            caller_number=caller_number,
            transcript=transcript.strip(" | "),
            detected_intent=intent,
            duration=duration,
            summary=summary,
        )
        logger.info(f"Call ended. Duration={duration}s  Intent={intent}")

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="receptionist-groq",
        )
    )
