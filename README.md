# Field Service Work Reporting Agent

An AI agent that helps field service technicians log their work — catching billing errors, certification violations, duplicate work, and missing materials automatically.

## Quick Start

### Docker (recommended)

**Prerequisites:** Docker, an [Anthropic API key](https://console.anthropic.com/), and an [OpenAI API key](https://platform.openai.com/) (for voice).

```bash
# 1. Clone the repo
git clone https://github.com/rajathul/fieldagent.git
cd fieldagent

# 2. Add your API keys
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY and OPENAI_API_KEY

# 3. Build and run
docker build -t fieldagent .
docker run -p 8000:8000 --env-file .env fieldagent
```

### Build from source

```bash
pip install -r requirements.txt
python main.py
```

Open [http://localhost:8000](http://localhost:8000) for the chat UI, or [http://localhost:8000/dashboard](http://localhost:8000/dashboard) for the manager dashboard.

API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/session` | Create a new conversation session. Body: `{"worker_id": "W-001", "date": "2026-03-25"}` |
| `POST` | `/message` | Send a text message and get the agent's reply. Body: `{"session_id": "...", "content": "..."}` |
| `POST` | `/transcribe` | Upload a recorded audio blob, returns transcribed text via OpenAI Whisper. Body: multipart `audio` file |
| `POST` | `/speak` | Convert text to speech via OpenAI TTS, returns an MP3 stream. Body: `{"text": "..."}` |
| `GET`  | `/worklogs` | Query completed work logs. Params: `worker_id`, `customer_id`, `date_from`, `date_to` |
| `GET`  | `/stream` | Server-Sent Events stream for real-time dashboard updates |
| `GET`  | `/health` | Health check |

## Voice

The chat UI has a built-in push-to-talk mode. Click the mic button to switch into voice mode — tap to record, tap again to stop. The recording is transcribed by Whisper, sent to Claude, and the reply is spoken back via TTS. Click the keyboard icon to return to text input. Requires `OPENAI_API_KEY`.

## Test Workers

| ID | Name | Role | Notes |
|----|------|------|-------|
| W-001 | Pekka Virtanen | Senior Technician | HVAC, Refrigeration, has refrigerant cert |
| W-002 | Janne Korhonen | Technician | Electrical, Plumbing |
| W-003 | Lauri Heikkinen | Junior Technician | No refrigerant cert — good for testing cert blocks |
| W-004 | Sanna Makela | Technician | Refrigeration, HVAC, has refrigerant cert |

Test prompts and example conversations are in `data/test_prompts.json` and `data/example_conversations.json`.

## What the agent checks

| Check | Example |
|-------|---------|
| Certification | W-003 cannot handle refrigerant — stops before they start |
| Duplicate work | March HVAC already done at NPS — prevents repeat billing |
| Contract scope | GFS has no weekend/evening billing — flags and marks non-billable |
| Cost limits | GFS job over 500 EUR — requires Reijo Makinen approval |
| Missing materials | Expansion valve work → suggests refrigerant top-up and flare fittings |
| Rate selection | Sunday 11pm at NPS → emergency rate, minimum 2h charge |
| Non-catalog parts | NPS part over 200 EUR → requires site contact approval |
| FBL travel fee | Always adds 45 EUR travel to FrostBite invoices |

## Project Structure

```
main.py          FastAPI server — all endpoints + SSE broadcasting
agent.py         Claude agent — system prompt, conversation, work log extraction
data_store.py    Loads JSON reference data, provides lookups
database.py      SQLite — sessions, messages, work logs
models.py        Pydantic models (WorkLog, InvoiceItem, etc.)
chat.py          Interactive CLI for manual testing
data/            JSON reference files (contracts, workers, parts, history, test prompts)
fieldagent.db    SQLite database (created on first run)
```

## TODO

- Make work log extraction more efficient (currently a second LLM call after confirmation)
- Add real-time voice interaction (streaming STT/TTS instead of push-to-talk)
- Migrate database from SQLite to PostgreSQL
