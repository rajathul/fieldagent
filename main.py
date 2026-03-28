import os
import json
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from livekit.api import AccessToken, VideoGrants

load_dotenv()

from models import SessionCreate, MessageRequest, MessageResponse, WorkLog
from data_store import get_store
from database import init_db, create_session, get_session, save_message, get_messages, save_work_log, get_work_logs
from agent import FieldServiceAgent

app = FastAPI(title="Field Service Work Reporting Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SSE broadcaster ──────────────────────────────────────────
# Holds all active dashboard SSE queues
_sse_clients: list[asyncio.Queue] = []
_event_loop: asyncio.AbstractEventLoop | None = None

async def broadcast(event: str, data: dict):
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_clients.remove(q)

# Initialise DB and data on startup
@app.on_event("startup")
async def startup():
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    init_db()
    store = get_store()
    print(f"[startup] Loaded {len(store.workers['workers'])} workers, "
          f"{len(store.contracts['customers'])} customers, "
          f"{len(store.work_history['work_records'])} history records")


@app.post("/session")
def create_new_session(body: SessionCreate) -> dict:
    """
    Start a new conversation session for a worker.
    Returns a session_id that must be passed with every subsequent message.
    """
    store = get_store()
    worker = store.get_worker(body.worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {body.worker_id} not found")

    session_id = create_session(body.worker_id, body.date)
    return {
        "session_id": session_id,
        "worker_id": body.worker_id,
        "worker_name": worker["name"],
        "date": body.date,
    }


@app.post("/message")
def send_message(body: MessageRequest) -> MessageResponse:
    """
    Send a message from the worker. Returns the agent's response.
    If the work log is finalized (worker confirmed), also returns the work_log.
    """
    session = get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    worker_id = session["worker_id"]
    date = session["session_date"]

    # Save the worker's message
    save_message(body.session_id, "worker", body.content)

    # Get full history (now includes the new message)
    history = get_messages(body.session_id)

    # Get agent response
    store = get_store()
    agent = FieldServiceAgent(store)
    raw_response = agent.chat(worker_id, date, history)

    finalized = agent.is_finalized(raw_response)
    clean_response = agent.clean_response(raw_response)

    # Save agent response (without the internal marker)
    save_message(body.session_id, "agent", clean_response)

    work_log = None
    if finalized:
        # Second call: extract structured work log
        full_history = get_messages(body.session_id)
        work_log = agent.extract_work_log(worker_id, date, full_history)
        if work_log:
            save_work_log(body.session_id, work_log)
            print(f"[main] Work log saved for session {body.session_id}: "
                  f"billable={work_log.billable}, status={work_log.status}")
            # Push to all connected dashboards
            if _event_loop is not None:
                asyncio.run_coroutine_threadsafe(broadcast("worklog", {
                    "session_id": body.session_id,
                    "worker_id": worker_id,
                    "work_log": work_log.model_dump(),
                }), _event_loop)

    return MessageResponse(
        session_id=body.session_id,
        response=clean_response,
        work_log=work_log,
        finalized=finalized,
    )


@app.get("/worklogs")
def query_work_logs(
    worker_id: str | None = None,
    customer_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Manager view: query completed work logs.
    All parameters are optional filters.
    """
    return get_work_logs(worker_id, customer_id, date_from, date_to)


@app.get("/stream")
async def sse_stream():
    """Server-Sent Events stream for real-time dashboard updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_clients.append(queue)

    async def event_generator():
        # Send current snapshot on connect
        logs = get_work_logs()
        yield f"event: snapshot\ndata: {json.dumps(logs)}\n\n"
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=25)
                yield msg
        except asyncio.TimeoutError:
            yield "event: ping\ndata: {}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _sse_clients:
                _sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/livekit-token")
def get_livekit_token(session_id: str, worker_id: str, date: str):
    lk_url = os.getenv("LIVEKIT_URL")
    lk_key = os.getenv("LIVEKIT_API_KEY")
    lk_secret = os.getenv("LIVEKIT_API_SECRET")
    if not all([lk_url, lk_key, lk_secret]):
        raise HTTPException(status_code=500, detail="LiveKit env vars not configured")

    room_name = f"fieldagent-{session_id}"
    metadata = json.dumps({"worker_id": worker_id, "date": date, "session_id": session_id})
    token = (
        AccessToken(lk_key, lk_secret)
        .with_identity(worker_id)
        .with_name(worker_id)
        .with_metadata(metadata)
        .with_grants(VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )
    return {"token": token, "room": room_name, "url": lk_url}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def serve_chat():
    return FileResponse("chat_ui.html")


@app.get("/dashboard")
def serve_dashboard():
    return FileResponse("dashboard.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)