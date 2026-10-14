"""SQLite storage for the two local systems: the invoice system and the CRM."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    vendor         TEXT,
    amount         TEXT NOT NULL,          -- stored as a decimal string, e.g. "12500.00"
    currency       TEXT NOT NULL DEFAULT 'INR',
    due_date       TEXT NOT NULL,          -- ISO date, YYYY-MM-DD
    status         TEXT NOT NULL DEFAULT 'pending',
    source_file    TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id         TEXT PRIMARY KEY,           -- e.g. CUST-1001
    name       TEXT NOT NULL,
    email      TEXT UNIQUE NOT NULL,
    phone      TEXT,
    address    TEXT,
    plan       TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    system    TEXT NOT NULL,               -- 'invoice' or 'crm'
    actor     TEXT NOT NULL,               -- 'agent' or 'ui'
    action    TEXT NOT NULL,
    record_id TEXT NOT NULL,
    details   TEXT NOT NULL
);
"""

SEED_CUSTOMERS = [
    ("CUST-1001", "Aarav Mehta", "aarav.mehta@example.com", "+919810011001",
     "12 MG Road, Bengaluru 560001", "basic", "active"),
    ("CUST-1002", "Priya Sharma", "priya.sharma@example.com", "+919820022002",
     "45 Park Street, Kolkata 700016", "standard", "active"),
    ("CUST-1003", "Rohan Gupta", "rohan.gupta@example.com", "+919830033003",
     "7 Civil Lines, Jaipur 302006", "premium", "active"),
    ("CUST-1004", "Sneha Iyer", "sneha.iyer@example.com", "+919840044004",
     "22 Anna Salai, Chennai 600002", "basic", "active"),
    ("CUST-1005", "Vikram Singh", "vikram.singh@example.com", "+919850055005",
     "9 Sector 17, Chandigarh 160017", "standard", "active"),
    ("CUST-1006", "Ananya Reddy", "ananya.reddy@example.com", "+919860066006",
     "3 Banjara Hills, Hyderabad 500034", "basic", "inactive"),
    ("CUST-1007", "Rahul Verma", "rahul.verma@example.com", "+919870077007",
     "18 FC Road, Pune 411004", "standard", "active"),
    ("CUST-1008", "Rahul Verma", "rahul.v.work@example.com", "+919880088008",
     "56 Linking Road, Mumbai 400050", "basic", "active"),
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path, reset: bool = False) -> None:
    """Create tables and load the seed customers. reset=True wipes everything first."""
    with connect(db_path) as conn:
        if reset:
            conn.executescript(
                "DROP TABLE IF EXISTS invoices; DROP TABLE IF EXISTS customers; "
                "DROP TABLE IF EXISTS audit_log;"
            )
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            ts = now_iso()
            conn.executemany(
                "INSERT INTO customers (id, name, email, phone, address, plan, status, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [row + (ts,) for row in SEED_CUSTOMERS],
            )


def write_audit(conn: sqlite3.Connection, system: str, actor: str, action: str,
                record_id: str, details: dict) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, system, actor, action, record_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (now_iso(), system, actor, action, record_id, json.dumps(details)),
    )
