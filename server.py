"""
FastAPI server for LiveKit + Plivo AI Receptionist

Endpoints:
  GET  /health  - Health check for Railway
  GET  /        - Service info
  POST /call    - Initiate outbound call via LiveKit SIP + Plivo
  GET  /logs    - View recent call logs
"""

import os

import plivo
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger
from livekit.api import LiveKitAPI, CreateSIPParticipantRequest

from db import init_db, get_connection

load_dotenv()

app = FastAPI(title="LiveKit + Groq AI Receptionist")

# LiveKit SIP trunk ID — set this after creating the trunk in LiveKit Cloud
SIP_TRUNK_ID = os.getenv("LIVEKIT_SIP_TRUNK_ID", "")


@app.on_event("startup")
async def startup():
    logger.info("Starting LiveKit AI Receptionist server...")
    init_db()
    logger.info("Server ready.")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "livekit-groq-receptionist",
        "version": "1.0.0",
    }


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "livekit-groq-receptionist",
        "endpoints": {
            "/health": "Health check",
            "/call": "Initiate outbound call (POST)",
            "/logs": "View recent call logs",
        },
    }


@app.post("/call")
async def call(request: Request):
    """
    Initiate an outbound call.

    LiveKit SIP flow:
      1. Server creates a SIP participant in a LiveKit room
      2. LiveKit dials out via the configured Plivo SIP trunk
      3. The agent worker picks up the room and handles the conversation

    If no SIP trunk is configured, falls back to Plivo REST API
    to place the call and returns call info.
    """
    body = await request.json()
    to_number = body.get("to")
    if not to_number:
        return JSONResponse({"error": "Missing 'to' field"}, status_code=400)

    # ── Option A: LiveKit SIP outbound (preferred) ────────────────────────
    if SIP_TRUNK_ID:
        try:
            lk_api = LiveKitAPI(
                url=os.getenv("LIVEKIT_URL"),
                api_key=os.getenv("LIVEKIT_API_KEY"),
                api_secret=os.getenv("LIVEKIT_API_SECRET"),
            )

            room_name = f"call-{to_number.replace('+', '')}"
            from_number = os.getenv("PLIVO_PHONE_NUMBER", "")

            sip_participant = await lk_api.sip.create_sip_participant(
                CreateSIPParticipantRequest(
                    sip_trunk_id=SIP_TRUNK_ID,
                    sip_call_to=to_number,
                    room_name=room_name,
                    participant_identity=f"sip-{to_number}",
                    participant_name=to_number,
                )
            )
            await lk_api.aclose()

            logger.info(f"SIP outbound call to {to_number} in room {room_name}")
            return {
                "status": "call_initiated",
                "method": "livekit_sip",
                "room": room_name,
                "participant_id": sip_participant.participant_id if hasattr(sip_participant, 'participant_id') else "created",
            }
        except Exception as e:
            logger.error(f"LiveKit SIP call failed: {e}")
            return JSONResponse({"error": str(e)}, status_code=502)

    # ── Option B: Plivo REST API fallback ─────────────────────────────────
    auth_id = os.getenv("PLIVO_AUTH_ID")
    auth_token = os.getenv("PLIVO_AUTH_TOKEN")
    from_number = os.getenv("PLIVO_PHONE_NUMBER")

    if not all([auth_id, auth_token, from_number]):
        return JSONResponse(
            {"error": "Neither SIP trunk nor Plivo credentials configured"},
            status_code=500,
        )

    client = plivo.RestClient(auth_id, auth_token)
    try:
        response = client.calls.create(
            from_=from_number,
            to_=to_number,
            answer_url=body.get("answer_url", ""),
            answer_method="POST",
        )
        logger.info(f"Plivo outbound call to {to_number}, UUID: {response.request_uuid}")
        return {
            "status": "call_initiated",
            "method": "plivo_rest",
            "request_uuid": response.request_uuid,
        }
    except plivo.exceptions.PlivoRestError as e:
        logger.error(f"Plivo API error: {e}")
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/logs")
async def get_logs():
    """View recent call logs from the database."""
    conn = get_connection()
    if not conn:
        return JSONResponse({"error": "Database not configured"}, status_code=503)

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, caller_number, transcript, summary, detected_intent, duration, created_at
            FROM livekit_groq_call_logs
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()

        logs = []
        for row in rows:
            logs.append({
                "id": row[0],
                "caller_number": row[1],
                "transcript": row[2],
                "summary": row[3],
                "detected_intent": row[4],
                "duration_seconds": row[5],
                "timestamp": row[6].isoformat() if row[6] else None,
            })

        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        logger.error(f"Failed to fetch logs: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
