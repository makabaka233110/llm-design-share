"""Learning store: one SQLite file for every record that is not reference material.

Reference passages live as Markdown in KB_DIR (indexed by Memsearch); their
metadata (owner, topic, version, review status, priority) lives in `docs` here.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("MIANBI_DATA", Path(__file__).parent.parent / "data")).resolve()
KB_DIR = DATA_DIR / "kb"
DB_PATH = DATA_DIR / "mianbi.db"

# Columns stored as JSON text and decoded on read.
JSON_COLS = {"scores", "feedback", "evidence", "eval_points", "sources", "analysis"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
  goals TEXT DEFAULT '', criteria TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, domain_id INTEGER,
  title TEXT, topic TEXT DEFAULT '', source TEXT DEFAULT '', version INTEGER DEFAULT 1,
  reviewed INTEGER DEFAULT 1, priority REAL DEFAULT 2, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, domain_id INTEGER,
  text TEXT NOT NULL, concept TEXT DEFAULT '', kind TEXT DEFAULT 'knowledge', origin TEXT DEFAULT 'manual', parent_id INTEGER,
  session_id INTEGER, context TEXT DEFAULT '', eval_points TEXT, sources TEXT, difficulty TEXT DEFAULT '',
  created_at TEXT);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, question_id INTEGER NOT NULL,
  mode TEXT, answer TEXT NOT NULL, version INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL, status TEXT,
  scores TEXT, feedback TEXT, evidence TEXT, evidence_mode TEXT, history_aware INTEGER DEFAULT 0,
  rubric_version TEXT, model TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS hints(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, question_id INTEGER, text TEXT,
  pref_version INTEGER, personalized INTEGER DEFAULT 1, rating TEXT, comment TEXT DEFAULT '',
  created_at TEXT, feedback_at TEXT);
CREATE TABLE IF NOT EXISTS hint_prefs(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, version INTEGER,
  summary TEXT DEFAULT '', source TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, domain_id INTEGER,
  role TEXT DEFAULT '', kind TEXT, finished INTEGER DEFAULT 0, summary TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, role TEXT, content TEXT,
  question_id INTEGER, attempt_id INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS reflections(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, domain_id INTEGER,
  title TEXT, transcript TEXT, analysis TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS gaps(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, domain_id INTEGER, text TEXT,
  origin TEXT, origin_id INTEGER, question_id INTEGER, confirmed INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, domain_id INTEGER,
  collection TEXT DEFAULT 'General', question TEXT, answer TEXT, policy TEXT DEFAULT 'sm2',
  status TEXT DEFAULT 'learning', ef REAL DEFAULT 2.5, interval REAL DEFAULT 0, reps INTEGER DEFAULT 0,
  streak INTEGER DEFAULT 0, due_at TEXT, gap_id INTEGER, question_id INTEGER, sources TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, card_id INTEGER, rating TEXT, user_answer TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS llm_log(id INTEGER PRIMARY KEY, user_id TEXT, task TEXT, model TEXT, ms INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, ok INTEGER, error TEXT, created_at TEXT);
"""

# Tables holding per-user rows (used for "delete my data").
USER_TABLES = ["domains", "docs", "questions", "attempts", "hints", "hint_prefs", "sessions",
               "reflections", "gaps", "cards", "llm_log"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def init() -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def _encode(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def rows(sql: str, *args) -> list[dict]:
    with connect() as c:
        return [_decode(r) for r in c.execute(sql, args)]


def row(sql: str, *args) -> dict | None:
    r = rows(sql, *args)
    return r[0] if r else None


def run(sql: str, *args) -> int:
    with connect() as c:
        return c.execute(sql, [_encode(a) for a in args]).lastrowid


def insert(table: str, **fields) -> int:
    fields.setdefault("created_at", now())
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    return run(f"INSERT INTO {table}({cols}) VALUES({marks})", *fields.values())


def update(table: str, id: int, **fields) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    run(f"UPDATE {table} SET {sets} WHERE id=?", *fields.values(), id)


def owned(table: str, id: int, user: str) -> dict:
    """Fetch a row that must belong to `user` (record isolation)."""
    from fastapi import HTTPException
    r = row(f"SELECT * FROM {table} WHERE id=? AND user_id=?", id, user)
    if not r:
        raise HTTPException(404, f"{table} {id} not found")
    return r


def delete_user(user: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM evaluations WHERE attempt_id IN (SELECT id FROM attempts WHERE user_id=?)", (user,))
        c.execute("DELETE FROM turns WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)", (user,))
        c.execute("DELETE FROM reviews WHERE card_id IN (SELECT id FROM cards WHERE user_id=?)", (user,))
        for t in USER_TABLES:
            c.execute(f"DELETE FROM {t} WHERE user_id=?", (user,))
