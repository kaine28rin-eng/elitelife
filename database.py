#!/usr/bin/env python3
"""
Elite Life Bot — Database Layer
SQLite wrapper used by both bot.py and server.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "elitelife.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS subjects (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT NOT NULL,
                emoji TEXT DEFAULT '📚'
            );

            CREATE TABLE IF NOT EXISTS modules (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL REFERENCES subjects(id),
                name       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS files (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER NOT NULL REFERENCES modules(id),
                file_id   TEXT NOT NULL,
                filename  TEXT NOT NULL,
                file_type TEXT DEFAULT 'document',
                tag       TEXT DEFAULT 'notes',
                added_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER UNIQUE NOT NULL,
                username   TEXT,
                first_name TEXT,
                last_name  TEXT,
                seen_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS file_downloads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER,
                username      TEXT,
                first_name    TEXT,
                file_db_id    INTEGER,
                filename      TEXT,
                downloaded_at TEXT
            );
        """)
        _seed(c)

def _seed(c):
    """Insert default subjects + modules if DB is empty."""
    if c.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] > 0:
        return

    subjects = [
        ("English Studies S4", "🎓"),
    ]
    for name, emoji in subjects:
        c.execute("INSERT INTO subjects(name,emoji) VALUES(?,?)", (name, emoji))

    subject_id = c.execute("SELECT id FROM subjects LIMIT 1").fetchone()[0]

    modules = [
        "Introduction to Linguistics",
        "Discourse Analysis",
        "Introduction to Research",
        "African Literature & Culture",
        "Cultural Studies",
        "Introduction to Translation",
        "Foreign Language (French)",
    ]
    for m in modules:
        c.execute("INSERT INTO modules(subject_id,name) VALUES(?,?)", (subject_id, m))

# ── CRUD helpers ──────────────────────────────────────────────────────────────

def get_subjects():
    with get_conn() as c:
        return c.execute("SELECT * FROM subjects").fetchall()

def get_modules(subject_id):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM modules WHERE subject_id=? ORDER BY id",
            (subject_id,)).fetchall()

def get_module(module_id):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM modules WHERE id=?", (module_id,)).fetchone()

def get_files(module_id):
    with get_conn() as c:
        return c.execute(
            "SELECT * FROM files WHERE module_id=? ORDER BY id",
            (module_id,)).fetchall()

def add_file(module_id, file_id, filename, file_type="document", tag="notes"):
    with get_conn() as c:
        c.execute(
            "INSERT INTO files(module_id,file_id,filename,file_type,tag) VALUES(?,?,?,?,?)",
            (module_id, file_id, filename, file_type, tag))

def upsert_user(user):
    with get_conn() as c:
        c.execute("""
            INSERT INTO users(user_id, username, first_name, last_name, seen_at)
            VALUES(?,?,?,?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                seen_at    = excluded.seen_at
        """, (
            user.id,
            getattr(user, 'username', None),
            getattr(user, 'first_name', None),
            getattr(user, 'last_name', None),
        ))
