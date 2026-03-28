"""
LiveKit voice agent for the Field Service Work Reporting system.

Uses OpenAI Whisper for STT and OpenAI TTS for speech synthesis,
while keeping the existing FieldServiceAgent (Claude) as the brain.
Intercepts every user turn via on_user_turn_completed so the default
LLM is bypassed entirely.

Usage:
    python voice_agent.py dev       # development mode
    python voice_agent.py start     # production worker

Required env vars (add to .env):
    LIVEKIT_URL          wss://your-project.livekit.cloud
    LIVEKIT_API_KEY      your LiveKit API key
    LIVEKIT_API_SECRET   your LiveKit API secret
    OPENAI_API_KEY       for STT (Whisper) and TTS
    ANTHROPIC_API_KEY    already set — used by FieldServiceAgent

Client participant metadata (JSON string):
    {"worker_id": "W-001", "date": "2026-03-28"}
"""

import asyncio
import json
import logging
import os
from datetime import date as date_cls

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, RoomInputOptions, StopResponse, WorkerOptions
from livekit.plugins import openai, silero

load_dotenv()

from agent import FieldServiceAgent
from data_store import get_store
from database import create_session, get_messages, init_db, save_message, save_work_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fieldagent-voice")


class FieldVoiceAgent(Agent):
    def __init__(self, session_id: str, worker_id: str, work_date: str):
        super().__init__(
            instructions=(
                "You are a field service work reporting assistant. "
                "Help the worker log their completed work accurately."
            )
        )
        self.session_id = session_id
        self.worker_id = worker_id
        self.work_date = work_date
        # Reuse the same Claude configuration as the existing text flow.
        self._field_agent = FieldServiceAgent(get_store())

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        user_text = (new_message.text_content or "").strip()
        if not user_text:
            raise StopResponse()

        logger.info("Worker said: %r", user_text)

        # Persist utterance and fetch full history for Claude
        save_message(self.session_id, "worker", user_text)
        history = get_messages(self.session_id)

        # Run the synchronous Claude call off the event loop
        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(
            None,
            lambda: self._field_agent.chat(self.worker_id, self.work_date, history),
        )

        finalized = self._field_agent.is_finalized(raw_response)
        clean_response = self._field_agent.clean_response(raw_response)

        save_message(self.session_id, "agent", clean_response)
        logger.info("Agent reply (finalized=%s): %r", finalized, clean_response[:80])

        if finalized:
            full_history = get_messages(self.session_id)
            work_log = await loop.run_in_executor(
                None,
                lambda: self._field_agent.extract_work_log(
                    self.worker_id, self.work_date, full_history
                ),
            )
            if work_log:
                save_work_log(self.session_id, work_log)
                logger.info(
                    "Work log saved: session=%s billable=%s status=%s",
                    self.session_id, work_log.billable, work_log.status,
                )

        # Speak the response and skip default LLM generation
        await self.session.say(clean_response)
        raise StopResponse()


async def entrypoint(ctx: JobContext):
    init_db()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for LiveKit STT/TTS")

    await ctx.connect()
    logger.info("Voice agent connected to room: %s", ctx.room.name)

    participant = await ctx.wait_for_participant()

    # Parse worker_id and date from participant metadata
    metadata: dict = {}
    if participant.metadata:
        try:
            metadata = json.loads(participant.metadata)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse participant metadata: %r", participant.metadata)

    worker_id: str = metadata.get("worker_id", "W-001")
    work_date: str = metadata.get("date", date_cls.today().isoformat())
    session_id: str = metadata.get("session_id") or create_session(worker_id, work_date)
    logger.info("Voice session: worker=%s date=%s session=%s", worker_id, work_date, session_id)

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=openai.STT(model="whisper-1"),
        llm=openai.LLM(model="gpt-4o-mini"),   # bypassed via StopResponse
        tts=openai.TTS(voice="alloy"),
    )

    # Greet by first name if we can look up the worker
    try:
        store = get_store()
        worker = store.get_worker(worker_id)
        first_name = worker.get("name", "").split()[0] if worker else ""
    except Exception:
        first_name = ""

    greeting = (
        f"Hi {first_name}! I'm your field service assistant. "
        "Tell me about the work you completed today and I'll help you log it."
        if first_name
        else "Hi! I'm your field service assistant. Tell me about the work you completed today."
    )

    await session.start(
        room=ctx.room,
        agent=FieldVoiceAgent(
            session_id=session_id,
            worker_id=worker_id,
            work_date=work_date,
        ),
        room_input_options=RoomInputOptions(),
    )

    await session.say(greeting)


if __name__ == "__main__":
    agents.cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
