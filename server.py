#!/usr/bin/env python3
"""
Elite Life — Mini App API Server
Wraps the SQLite database and serves JSON to miniapp.html.
Run alongside bot.py (different terminal / process).

Usage:
    pip install flask flask-cors --break-system-packages
    python server.py

Endpoints:
    GET  /api/modules          → all modules + files
    GET  /api/stats            → global stats
    GET  /api/users            → all users + dl count
    GET  /api/users/<uid>/activity  → downloads by user
    GET  /api/dllog/<module_id>     → download log for module
    POST /api/send             → tell bot to send file to user (via queue)
    DELETE /api/files/<fid>    → delete a file record
    DELETE /api/modules/<mid>/files → clear all files in module
"""

import json, os, datetime, threading, queue
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
import database as db

# ── CONFIG ────────────────────────────────────────────────────────────────────
HOST      = "0.0.0.0"
PORT      = 8080
import os
from dotenv import load_dotenv
load_dotenv()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS","5852460298").split(",")]

# Shared queue — bot.py reads from this to send files
# (used when Mini App triggers a download)
send_queue = queue.Queue()

app = Flask(__name__)
CORS(app, origins="*")   # Allow Telegram Mini App origin

# ── UTILS ─────────────────────────────────────────────────────────────────────
MODULE_COLORS = ["m0","m1","m2","m3","m4","m5","m6"]
MODULE_EMOJIS = {
    "Introduction to Linguistics":  "📖",
    "Discourse Analysis":           "🗣️",
    "Introduction to Research":     "🔬",
    "African Literature & Culture": "🌍",
    "Cultural Studies":             "🧠",
    "Introduction to Translation":  "🔄",
    "Foreign Language (French)":    "🇫🇷",
}

def row_to_dict(row):
    """Convert sqlite3.Row to plain dict."""
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows):
    return [dict(r) for r in rows]

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def get_uid_from_request() -> int | None:
    """
    Read Telegram user ID from request header or query param.
    Mini App sends: X-Telegram-User-Id: <id>
    """
    uid = request.headers.get("X-Telegram-User-Id") or request.args.get("uid")
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None

def require_admin():
    uid = get_uid_from_request()
    if not uid or not is_admin(uid):
        abort(403, description="Admin only")

def log_download(user_id, username, first_name, file_db_id, filename):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with db.get_conn() as c:
        c.execute(
            "INSERT INTO file_downloads"
            "(user_id,username,first_name,file_db_id,filename,downloaded_at)"
            " VALUES(?,?,?,?,?,?)",
            (user_id, username or "", first_name or "", file_db_id, filename, now))

# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok", "time": datetime.datetime.now().isoformat()})


@app.route("/api/modules")
def get_modules():
    """Return all subjects → modules → files."""
    subjects = db.get_subjects()
    result   = []
    color_i  = 0
    for s in subjects:
        for m in db.get_modules(s["id"]):
            files = rows_to_list(db.get_files(m["id"]))
            result.append({
                "id":    m["id"],
                "name":  m["name"],
                "emoji": MODULE_EMOJIS.get(m["name"], "📂"),
                "color": MODULE_COLORS[color_i % len(MODULE_COLORS)],
                "files": [
                    {
                        "id":        f["id"],
                        "filename":  f["filename"],
                        "file_type": f["file_type"],
                        "tag":       f.get("tag", "notes"),
                    }
                    for f in files
                ],
            })
            color_i += 1
    return jsonify(result)


@app.route("/api/stats")
def get_stats():
    """Global usage stats. Admin only."""
    require_admin()
    with db.get_conn() as c:
        total_users     = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_downloads = c.execute("SELECT COUNT(*) FROM file_downloads").fetchone()[0]

        # Top module
        top_row = c.execute(
            "SELECT f.module_id, COUNT(*) as cnt "
            "FROM file_downloads fd JOIN files f ON fd.file_db_id=f.id "
            "GROUP BY f.module_id ORDER BY cnt DESC LIMIT 1").fetchone()

        top_module = None
        top_count  = 0
        if top_row:
            mod = c.execute(
                "SELECT name FROM modules WHERE id=?",
                (top_row["module_id"],)).fetchone()
            top_module = mod["name"] if mod else "?"
            top_count  = top_row["cnt"]

        # Per-module download counts
        mod_counts_raw = c.execute(
            "SELECT f.module_id, COUNT(*) as cnt "
            "FROM file_downloads fd JOIN files f ON fd.file_db_id=f.id "
            "GROUP BY f.module_id").fetchall()
        mod_counts = {r["module_id"]: r["cnt"] for r in mod_counts_raw}

        # File counts per module
        file_counts_raw = c.execute(
            "SELECT module_id, COUNT(*) as cnt FROM files GROUP BY module_id").fetchall()
        file_counts = {r["module_id"]: r["cnt"] for r in file_counts_raw}

    return jsonify({
        "total_users":     total_users,
        "total_downloads": total_downloads,
        "top_module":      top_module,
        "top_count":       top_count,
        "mod_downloads":   mod_counts,
        "file_counts":     file_counts,
    })


@app.route("/api/users")
def get_users():
    """All users with download count. Admin only."""
    require_admin()
    with db.get_conn() as c:
        users = c.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
        result = []
        for u in users:
            dl_count = c.execute(
                "SELECT COUNT(*) FROM file_downloads WHERE user_id=?",
                (u["user_id"],)).fetchone()[0]
            result.append({
                "user_id":    u["user_id"],
                "first_name": u["first_name"] or "",
                "username":   u.get("username") or "",
                "dl_count":   dl_count,
            })
    return jsonify(result)


@app.route("/api/users/<int:user_id>/activity")
def get_user_activity(user_id):
    """Download history for a specific user. Admin only."""
    require_admin()
    with db.get_conn() as c:
        logs = c.execute(
            "SELECT fd.*, f.module_id FROM file_downloads fd "
            "LEFT JOIN files f ON fd.file_db_id = f.id "
            "WHERE fd.user_id=? ORDER BY fd.downloaded_at DESC LIMIT 50",
            (user_id,)).fetchall()
        user = c.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return jsonify({
        "user":     row_to_dict(user),
        "activity": rows_to_list(logs),
    })


@app.route("/api/dllog/<int:module_id>")
def get_dl_log(module_id):
    """Download log for a module. Admin only."""
    require_admin()
    with db.get_conn() as c:
        fids = [r["id"] for r in
                c.execute("SELECT id FROM files WHERE module_id=?", (module_id,)).fetchall()]
        if not fids:
            return jsonify([])
        ph   = ",".join("?" * len(fids))
        logs = c.execute(
            f"SELECT * FROM file_downloads WHERE file_db_id IN({ph})"
            f" ORDER BY downloaded_at DESC LIMIT 100",
            fids).fetchall()
    return jsonify(rows_to_list(logs))


@app.route("/api/send", methods=["POST"])
def request_send():
    """
    Mini App → server → bot queue → user gets file in Telegram chat.
    Body: { action: "download"|"getall", file_id?: int, module_id?: int,
            user_id: int, username: str, first_name: str }
    """
    body = request.get_json(silent=True) or {}
    uid  = body.get("user_id")
    if not uid:
        return jsonify({"error": "user_id required"}), 400

    action = body.get("action")
    if action not in ("download", "getall"):
        return jsonify({"error": "invalid action"}), 400

    # Log the download intent
    if action == "download":
        fid = body.get("file_id")
        with db.get_conn() as c:
            f = c.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f:
            return jsonify({"error": "file not found"}), 404
        log_download(uid, body.get("username",""), body.get("first_name",""), fid, f["filename"])

    # Push to queue (bot.py dequeues and sends)
    send_queue.put({
        "action":    action,
        "user_id":   uid,
        "file_id":   body.get("file_id"),
        "module_id": body.get("module_id"),
    })

    return jsonify({"status": "queued"})


@app.route("/api/files/<int:file_id>", methods=["DELETE"])
def delete_file(file_id):
    """Delete a single file. Admin only."""
    require_admin()
    with db.get_conn() as c:
        row = c.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        c.execute("DELETE FROM files WHERE id=?", (file_id,))
    return jsonify({"deleted": file_id, "filename": row["filename"]})


@app.route("/api/modules/<int:module_id>/files", methods=["DELETE"])
def clear_module(module_id):
    """Delete all files in a module. Admin only."""
    require_admin()
    with db.get_conn() as c:
        cnt = c.execute(
            "SELECT COUNT(*) as c FROM files WHERE module_id=?",
            (module_id,)).fetchone()["c"]
        c.execute("DELETE FROM files WHERE module_id=?", (module_id,))
    return jsonify({"deleted_count": cnt, "module_id": module_id})


# ── ERROR HANDLERS ────────────────────────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    return jsonify({"error": str(e.description)}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404

@app.errorhandler(500)
def internal(e):
    return jsonify({"error": "internal server error"}), 500


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    db.init_db()
    # Ensure download log table
    with db.get_conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS file_downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, first_name TEXT,
            file_db_id INTEGER, filename TEXT, downloaded_at TEXT)""")

    print(f"🚀  Elite Life API Server running on http://{HOST}:{PORT}")
    print(f"📡  Endpoints: /api/modules  /api/stats  /api/users  /api/send")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
