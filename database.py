import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from models import WorkLog

DB_PATH = Path(__file__).parent / "fieldagent.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                worker_id TEXT NOT NULL,
                session_date TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL CHECK(role IN ('worker', 'agent')),
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS work_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
                customer_id TEXT,
                worker_id TEXT,
                site_id TEXT,
                log_date TEXT,
                status TEXT,
                billable INTEGER,
                log_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)


def create_session(worker_id: str, session_date: str) -> str:
    session_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, worker_id, session_date) VALUES (?, ?, ?)",
            (session_id, worker_id, session_date),
        )
    return session_id


def save_message(session_id: str, role: str, content: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )


def get_messages(session_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def get_session(session_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def save_work_log(session_id: str, work_log: WorkLog):
    log_dict = work_log.model_dump()
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO work_logs
               (session_id, customer_id, worker_id, site_id, log_date, status, billable, log_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                work_log.customer_id,
                work_log.worker_id,
                work_log.site_id,
                work_log.date,
                work_log.status,
                1 if work_log.billable else 0,
                json.dumps(log_dict),
            ),
        )


def get_work_logs(
    worker_id: str | None = None,
    customer_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    query = "SELECT log_json FROM work_logs WHERE 1=1"
    params = []
    if worker_id:
        query += " AND worker_id = ?"
        params.append(worker_id)
    if customer_id:
        query += " AND customer_id = ?"
        params.append(customer_id)
    if date_from:
        query += " AND log_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND log_date <= ?"
        params.append(date_to)
    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [json.loads(row["log_json"]) for row in rows]
