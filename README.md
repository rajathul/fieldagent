# Field Service Work Reporting Agent

An AI agent that helps field service technicians log their work correctly — catching billing errors, certification violations, duplicate work, and missing materials automatically.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your API key
cp .env.example .env
# Edit .env and add your Anthropic API key

# 3. Make sure all data files are in data/
ls data/
# Should show: contracts.json, workers.json, work_history.json,
#              parts_catalog.json, work_queue.json, example_conversations.json,
#              work_log_schema.json, invoice_item_schema.json, test_prompts.json
```

## Usage

### Option 1: Interactive CLI (best for manual testing)

```bash
# Chat as Pekka Virtanen (W-001, Senior Technician)
python chat.py --worker W-001

# Chat as Lauri Heikkinen (W-003, uncertified — good for testing cert blocks)
python chat.py --worker W-003

# With explicit date
python chat.py --worker W-002 --date 2026-03-25
```

Workers:
- `W-001` — Pekka Virtanen, Senior Technician (HVAC, Refrigeration, has refrigerant cert)
- `W-002` — Janne Korhonen, Technician (Electrical, Plumbing)
- `W-003` — Lauri Heikkinen, Junior Technician (Ventilation, Dock — NO refrigerant cert)
- `W-004` — Sanna Makela, Technician (Refrigeration, HVAC — has refrigerant cert)

### Option 2: Run automated tests

```bash
# Run all 10 test scenarios
python test_runner.py

# Run a single test
python test_runner.py --id GS-01

# Run all and save conversation logs to output/
python test_runner.py --save
```

Test IDs: GS-01 through GS-10 (easy → hard)

### Option 3: REST API

```bash
# Start the server
python main.py
# or: uvicorn main:app --reload

# API is at http://localhost:8000
# Docs at http://localhost:8000/docs
```

API endpoints:
```
POST /session          Create session: {"worker_id": "W-001", "date": "2026-03-25"}
POST /message          Send message:   {"session_id": "...", "content": "..."}
GET  /worklogs         Query logs:     ?worker_id=W-001&date_from=2026-03-01
GET  /health           Health check
```

## Architecture

```
main.py         FastAPI HTTP layer — 3 endpoints
agent.py        AI brain — system prompt + conversation + work log extraction
data_store.py   Loads all JSON files, provides lookup helpers
database.py     SQLite — sessions, messages, work logs
models.py       Pydantic models for WorkLog, InvoiceItem, etc.
chat.py         Interactive CLI for manual testing
test_runner.py  Automated test harness (10 scenarios)
data/           All JSON source files (read-only)
output/         Test conversation logs (created by --save)
fieldagent.db   SQLite database (created on first run)
```

## What the agent checks

| Check | Example |
|-------|---------|
| Certification | W-003 cannot handle refrigerant — stops before they start |
| Duplicate work | March HVAC already done at NPS — prevents repeat visit |
| Contract scope | GFS has no weekend/evening billing — flags and marks non-billable |
| Cost limits | GFS job over 500 EUR — requires Reijo Makinen approval |
| Missing materials | Expansion valve work → suggests refrigerant top-up and flare fittings |
| Rate selection | Sunday 11pm at NPS → emergency rate, minimum 2h charge |
| Non-catalog parts | NPS part over 200 EUR → requires site contact approval |
| FBL travel fee | Always adds 45 EUR travel to FrostBite invoices |
