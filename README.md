# Field Service Work Reporting Agent
 
An AI agent that helps field service technicians log their work — catching billing errors, certification violations, duplicate work, and missing materials automatically.
 
## Quick Start (Docker)
 
**Prerequisites:** Docker and an [Anthropic API key](https://console.anthropic.com/).
 
```bash
# 1. Clone the repo
git clone https://github.com/rajathul/fieldagent.git
cd fieldagent
 
# 2. Add your API key
cp .env.example .env
# Edit .env and set: ANTHROPIC_API_KEY=sk-ant-...
 
# 3. Build and run
docker build -t fieldagent .
docker run -p 8000:8000 --env-file .env fieldagent
```
 
Open [http://localhost:8000](http://localhost:8000) for the chat UI, or [http://localhost:8000/dashboard](http://localhost:8000/dashboard) for the manager dashboard.
 
API docs are at [http://localhost:8000/docs](http://localhost:8000/docs).
 
## Test Workers
 
Pick a worker when starting a chat session:
 
| ID | Name | Role | Notes |
|----|------|------|-------|
| W-001 | Pekka Virtanen | Senior Technician | HVAC, Refrigeration, has refrigerant cert |
| W-002 | Janne Korhonen | Technician | Electrical, Plumbing |
| W-003 | Lauri Heikkinen | Junior Technician | NO refrigerant cert — good for testing cert blocks |
| W-004 | Sanna Makela | Technician | Refrigeration, HVAC, has refrigerant cert |
 
## API Endpoints
 
```
POST /session     Create session   {"worker_id": "W-001", "date": "2026-03-25"}
POST /message     Send message     {"session_id": "...", "content": "..."}
GET  /worklogs    Query work logs  ?worker_id=W-001&date_from=2026-03-01
GET  /stream      SSE stream       Real-time dashboard updates
GET  /health      Health check
```
 
## CLI Usage (without Docker)
 
```bash
pip install -r requirements.txt
 
# Interactive chat
python chat.py --worker W-001
python chat.py --worker W-003 --date 2026-03-25
 
# Automated test scenarios
python test_runner.py            # all 10 tests
python test_runner.py --id GS-01 # single test
python test_runner.py --save     # save logs to output/
 
# Run the API server directly
python main.py
```
 
## Project Structure
 
```
main.py          FastAPI server — endpoints + SSE broadcasting
agent.py         LLM agent — system prompt, conversation, work log extraction
data_store.py    Loads JSON reference data, provides lookups
database.py      SQLite — sessions, messages, work logs
models.py        Pydantic models (WorkLog, InvoiceItem, etc.)
chat.py          Interactive CLI for manual testing
test_runner.py   Automated test harness (10 scenarios)
data/            JSON reference files (contracts, workers, parts, etc.)
```
