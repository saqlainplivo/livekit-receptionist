"""
LiveKit AI Receptionist with Groq LLM

Stack:
- LLM:  Groq (Llama 3.3 70B)
- STT:  Deepgram Nova-2
- TTS:  Deepgram Aura (asteria voice)
- VAD:  Silero
- Turn: LiveKit turn-detector
"""

import os
import time
import logging

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    room_io,
)
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, groq, silero

from db import init_db, log_call

load_dotenv()

logger = logging.getLogger("receptionist")

# Try to import turn detector — not critical if unavailable
try:
    from livekit.plugins.turn_detector.multilingual import MultilingualModel
    TURN_DETECTOR = MultilingualModel()
except ImportError:
    try:
        from livekit.plugins import turn_detector
        TURN_DETECTOR = turn_detector.EOUModel()
    except Exception:
        TURN_DETECTOR = None
        logger.warning("Turn detector not available, using default")

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

# ── Agent with tool functions ──────────────────────────────────────────────────

class ReceptionistAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=RECEPTIONIST_INSTRUCTIONS)
        self._start_time = time.time()
        self._detected_intent = "unknown"

    async def on_enter(self):
        """Called when this agent becomes active — send an immediate greeting."""
        await self.session.say(
            "Hello! Thank you for calling TechCorp Solutions. "
            "My name is Rachel, your virtual receptionist. How can I help you today?",
            allow_interruptions=True,
        )

    @function_tool()
    async def get_business_hours(self, context: RunContext) -> str:
        """Get the current business hours for TechCorp Solutions."""
        logger.info("Tool called: get_business_hours")
        return (
            "TechCorp Solutions is open Monday through Friday, 9 AM to 6 PM Eastern Time. "
            "We are closed on weekends and major holidays."
        )

    @function_tool()
    async def get_office_location(self, context: RunContext) -> str:
        """Get the office location and address for TechCorp Solutions."""
        logger.info("Tool called: get_office_location")
        return (
            "TechCorp Solutions is located at 123 Innovation Drive, Suite 400, "
            "San Francisco, California 94105."
        )

    @function_tool()
    async def log_caller_intent(
        self,
        context: RunContext,
        intent: str,
        summary: str,
    ) -> str:
        """Log the detected caller intent for call tracking purposes.

        Args:
            intent: The detected intent category: sales, support, faq, or other
            summary: A brief summary of what the caller needs
        """
        logger.info(f"Tool called: log_caller_intent(intent={intent}, summary={summary})")
        self._detected_intent = intent
        return f"Intent recorded as: {intent}."

# ── App setup ──────────────────────────────────────────────────────────────────

server = AgentServer()


def prewarm(proc: JobProcess):
    """Pre-load the Silero VAD model so it's ready when a call arrives."""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="receptionist-groq")
async def entrypoint(ctx: JobContext):
    agent = ReceptionistAgent()

    session_kwargs = dict(
        stt=deepgram.STT(model="nova-2", language="en"),
        llm=groq.LLM(model="llama-3.3-70b-versatile"),
        tts=deepgram.TTS(voice="aura-asteria-en"),
        vad=ctx.proc.userdata["vad"],
    )
    if TURN_DETECTOR is not None:
        session_kwargs["turn_detection"] = TURN_DETECTOR

    session = AgentSession(**session_kwargs)

    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=room_io.RoomOptions(),
    )

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    cli.run_app(server)
