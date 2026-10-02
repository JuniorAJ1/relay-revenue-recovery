import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), csrf TEXT NOT NULL,
 expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (
 fingerprint TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leads (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
 phone TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'Manual',
 owner TEXT NOT NULL DEFAULT '', context TEXT NOT NULL DEFAULT '',
 last_touch TEXT NOT NULL, consent INTEGER NOT NULL DEFAULT 0,
 consent_note TEXT NOT NULL DEFAULT '', opted_out INTEGER NOT NULL DEFAULT 0,
 customer INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 0,
 cohort TEXT NOT NULL DEFAULT 'treatment' CHECK(cohort IN ('treatment','control')),
 status TEXT NOT NULL DEFAULT 'ready', created_at TEXT NOT NULL,
 provider TEXT NOT NULL DEFAULT '', external_id TEXT NOT NULL DEFAULT '',
 UNIQUE(provider, external_id));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, lead_id INTEGER REFERENCES leads(id), actor TEXT NOT NULL,
 kind TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
 subject TEXT NOT NULL, body TEXT NOT NULL, recipient TEXT NOT NULL,
 due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
 created_at TEXT NOT NULL, approved_by TEXT NOT NULL, provider_id TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'recovery',
 appointment_id INTEGER, claimed_at TEXT, appointment_starts_at TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS one_recovery_job ON jobs(lead_id)
 WHERE kind='recovery' AND status IN ('queued','sending','unknown');
CREATE TABLE IF NOT EXISTS appointments (
 id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
 starts_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'booked', owner TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_booking ON appointments(lead_id) WHERE status='booked';
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL REFERENCES leads(id),
 reference TEXT UNIQUE NOT NULL, cents INTEGER NOT NULL CHECK(cents>0),
 kind TEXT NOT NULL CHECK(kind IN ('settlement','refund')),
 settlement_id INTEGER REFERENCES payments(id), at TEXT NOT NULL, actor TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,due_at);
CREATE INDEX IF NOT EXISTS events_lead ON events(lead_id,id);
"""

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=15000')
    return db

@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise

def init(path, demo):
    db = connect(path)
    db.executescript(SCHEMA)
    with transaction(db):
        mode = db.execute("SELECT value FROM settings WHERE key='mode'").fetchone()
        expected = 'demo' if demo else 'live'
        if mode and mode['value'] != expected:
            raise RuntimeError('This database belongs to another mode. Use a separate DATABASE_PATH.')
        db.execute("INSERT OR IGNORE INTO settings VALUES ('mode',?)", (expected,))
        db.execute("INSERT OR IGNORE INTO settings VALUES ('schema_version','1')")
        columns={row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
        if 'appointment_starts_at' not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN appointment_starts_at TEXT NOT NULL DEFAULT ''")
        db.execute("UPDATE settings SET value='2' WHERE key='schema_version'")
    db.close()

def event(db, lead_id, actor, kind, detail):
    db.execute('INSERT INTO events(lead_id,actor,kind,detail,at) VALUES (?,?,?,?,?)',
               (lead_id, actor, kind, detail, now()))

def record(row):
    return dict(row) if row else None
