#!/usr/bin/env python3
"""
Elite Life Bot — FLSHM English Studies S4
Now with Telegram Mini App support.
"""
import asyncio, logging, datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
import database as db

# ── CONFIG ────────────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_IDS  = [int(x) for x in os.getenv("ADMIN_IDS","5852460298").split(",")]
MINI_APP_URL = os.getenv("MINI_APP_URL","https://your-username.github.io/elitelife/miniapp.html")
ADMIN_IDS   = [5852460298]

# 👇 Host miniapp.html on GitHub Pages / Vercel / Render (must be HTTPS)
MINI_APP_URL = "https://your-username.github.io/elitelife/miniapp.html"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

MODULE_EMOJIS = {
    "Introduction to Linguistics":  "📖",
    "Discourse Analysis":           "🗣️",
    "Introduction to Research":     "🔬",
    "African Literature & Culture": "🌍",
    "Cultural Studies":             "🧠",
    "Introduction to Translation":  "🔄",
    "Foreign Language (French)":    "🇫🇷",
}
def module_emoji(name): return MODULE_EMOJIS.get(name, "📂")

THIN_LINE = "─────────────────────"
DIVIDER   = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def is_admin(uid): return uid in ADMIN_IDS

def clean_filename(name):
    if not name: return ""
    for ext in [".pdf",".docx",".pptx",".txt",".xlsx",
                ".mp3",".mp4",".mkv",".jpg",".jpeg",".png",".zip"]:
        if name.lower().endswith(ext):
            name = name[:-len(ext)]; break
    return name.replace("_"," ").replace("-"," ").strip()

def _get_module(mid):
    try:
        return db.get_module(mid)
    except AttributeError:
        with db.get_conn() as c:
            return c.execute("SELECT * FROM modules WHERE id=?", (mid,)).fetchone()

def log_download(user_id, username, first_name, file_db_id, filename):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with db.get_conn() as c:
        c.execute(
            "INSERT INTO file_downloads"
            "(user_id,username,first_name,file_db_id,filename,downloaded_at)"
            " VALUES(?,?,?,?,?,?)",
            (user_id, username or "", first_name or "", file_db_id, filename, now))

def get_dl_log(module_id, limit=50):
    with db.get_conn() as c:
        fids = [r["id"] for r in
                c.execute("SELECT id FROM files WHERE module_id=?", (module_id,)).fetchall()]
        if not fids: return []
        ph = ",".join("?"*len(fids))
        return c.execute(
            f"SELECT * FROM file_downloads WHERE file_db_id IN({ph})"
            f" ORDER BY downloaded_at DESC LIMIT ?",
            (*fids, limit)).fetchall()

def get_all_users():
    with db.get_conn() as c:
        return c.execute("SELECT * FROM users ORDER BY id DESC").fetchall()

def get_user_activity(user_id, limit=20):
    with db.get_conn() as c:
        return c.execute(
            "SELECT * FROM file_downloads WHERE user_id=?"
            " ORDER BY downloaded_at DESC LIMIT ?",
            (user_id, limit)).fetchall()

def get_global_stats():
    with db.get_conn() as c:
        tu  = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        td  = c.execute("SELECT COUNT(*) FROM file_downloads").fetchone()[0]
        row = c.execute(
            "SELECT f.module_id, COUNT(*) as cnt "
            "FROM file_downloads fd JOIN files f ON fd.file_db_id=f.id "
            "GROUP BY f.module_id ORDER BY cnt DESC LIMIT 1").fetchone()
        top = None
        if row:
            m = _get_module(row["module_id"])
            top = (m["name"] if m else "?", row["cnt"])
        return tu, td, top

async def safe_edit(query, context, chat_id, text, reply_markup=None):
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        try: await query.message.delete()
        except Exception: pass
        await context.bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=reply_markup)

# ── KEYBOARDS ─────────────────────────────────────────────────────────────────
def main_reply_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Open Study App", web_app=WebAppInfo(url=MINI_APP_URL))]],
        resize_keyboard=True, one_time_keyboard=False)

def start_inline_kb(uid):
    rows = [[InlineKeyboardButton("📱 Open Study App", web_app=WebAppInfo(url=MINI_APP_URL))]]
    for s in db.get_subjects():
        for m in db.get_modules(s["id"]):
            rows.append([InlineKeyboardButton(
                f"{module_emoji(m['name'])}  {m['name']}",
                callback_data=f"mod:{m['id']}")])
    if is_admin(uid):
        rows.append([InlineKeyboardButton("⚙️  Admin Panel", callback_data="admin:panel")])
    rows.append([InlineKeyboardButton("ℹ️  Help", callback_data="help")])
    return InlineKeyboardMarkup(rows)

def module_kb(module_id, admin=False):
    files = db.get_files(module_id)
    rows  = [[InlineKeyboardButton("📱 Open in App", web_app=WebAppInfo(url=MINI_APP_URL))]]
    if files:
        rows.append([InlineKeyboardButton("📬  Get ALL Files", callback_data=f"getall:{module_id}")])
        rows.append([InlineKeyboardButton(f"── {len(files)} file(s) ──", callback_data="noop")])
        for f in files:
            icon = {"audio":"🎵","video":"🎬","photo":"🖼️"}.get(f["file_type"],"📄")
            lbl  = f["filename"][:36]+"…" if len(f["filename"])>38 else f["filename"]
            rows.append([InlineKeyboardButton(f"{icon}  {lbl}", callback_data=f"getfile:{f['id']}")])
    else:
        rows.append([InlineKeyboardButton("📭  No files yet", callback_data="noop")])
    if admin:
        rows.append([
            InlineKeyboardButton("➕ Add", callback_data=f"addfile:{module_id}"),
            InlineKeyboardButton("🗑️ Clear All", callback_data=f"clearmod:{module_id}"),
        ])
        rows.append([InlineKeyboardButton("👁️  Who Downloaded", callback_data=f"dllog:{module_id}")])
    rows.append([InlineKeyboardButton("🏠  Back", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def after_send_kb(module_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Open App", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("🔙  Back to Module", callback_data=f"mod:{module_id}")],
        [InlineKeyboardButton("🏠  Main Menu",      callback_data="home")],
    ])

def admin_study_kb():
    rows = []
    for s in db.get_subjects():
        rows.append([InlineKeyboardButton(f"── {s['emoji']}  {s['name']} ──", callback_data="noop")])
        for m in db.get_modules(s["id"]):
            count = len(db.get_files(m["id"]))
            rows.append([InlineKeyboardButton(
                f"{module_emoji(m['name'])}  {m['name']}   [{count}]",
                callback_data=f"adm:mod:{m['id']}")])
    rows.append([InlineKeyboardButton("🔙  Back", callback_data="admin:panel")])
    return InlineKeyboardMarkup(rows)

def admin_module_kb(module_id):
    files = db.get_files(module_id)
    rows  = [[InlineKeyboardButton(f"📁  {len(files)} file(s)", callback_data="noop")]]
    for f in files:
        icon = {"audio":"🎵","video":"🎬","photo":"🖼️"}.get(f["file_type"],"📄")
        lbl  = f["filename"][:28]+"…" if len(f["filename"])>30 else f["filename"]
        rows.append([
            InlineKeyboardButton(f"{icon}  {lbl}", callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"adm:del:{f['id']}:{module_id}"),
        ])
    rows.append([InlineKeyboardButton("➕  Add File", callback_data=f"adm:add:{module_id}")])
    if files:
        rows.append([InlineKeyboardButton("🗑️  Delete ALL", callback_data=f"adm:clear:{module_id}")])
    rows.append([InlineKeyboardButton("👁️  Downloads", callback_data=f"dllog:{module_id}")])
    rows.append([InlineKeyboardButton("🔙  Back", callback_data="admin:study")])
    return InlineKeyboardMarkup(rows)

def admin_panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Open App",      web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("📚  Study Files",  callback_data="admin:study")],
        [InlineKeyboardButton("👥  All Users",    callback_data="admin:users:0")],
        [InlineKeyboardButton("📊  Global Stats", callback_data="admin:stats")],
        [InlineKeyboardButton("🏠  Main Menu",    callback_data="home")],
    ])

def users_list_kb(page=0, per_page=10):
    users = get_all_users()
    start = page * per_page
    chunk = users[start:start+per_page]
    rows  = []
    for u in chunk:
        name  = u["first_name"] or "?"
        uname = f"@{u['username']}" if u.get("username") else f"#{u['user_id']}"
        rows.append([InlineKeyboardButton(f"👤  {name}  {uname}", callback_data=f"admin:user:{u['user_id']}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"admin:users:{page-1}"))
    if start+per_page < len(users): nav.append(InlineKeyboardButton("▶️", callback_data=f"admin:users:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙  Back", callback_data="admin:panel")])
    return InlineKeyboardMarkup(rows), len(users)

async def send_db_file(bot, chat_id, f):
    fid, ft, cap = f["file_id"], f["file_type"], f["filename"]
    try:
        if   ft == "audio": await bot.send_audio(chat_id, fid, caption=cap)
        elif ft == "video": await bot.send_video(chat_id, fid, caption=cap)
        elif ft == "photo": await bot.send_photo(chat_id, fid, caption=cap)
        else:               await bot.send_document(chat_id, fid, caption=cap)
    except Exception:
        try: await bot.send_document(chat_id, fid, caption=cap)
        except Exception as e: logger.error(f"send_db_file: {e}")

# ── COMMANDS ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user)
    await update.message.reply_text(
        f"👋 *Welcome, {user.first_name}!*\n`{THIN_LINE}`\n"
        f"🎓 *FLSHM · English Studies S4*\n_Hassan II University · Mohammedia_\n\n"
        f"Tap *📱 Open Study App* for the full experience,\nor pick a module below:",
        parse_mode="Markdown", reply_markup=main_reply_kb())
    await update.message.reply_text(
        "📚 *Choose a module:*", parse_mode="Markdown",
        reply_markup=start_inline_kb(user.id))

async def manage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admins only."); return
    await update.message.reply_text(
        f"📚 *Study Files Manager*\n`{THIN_LINE}`\nPick a module:",
        parse_mode="Markdown", reply_markup=admin_study_kb())

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ *Cancelled.*", parse_mode="Markdown", reply_markup=main_reply_kb())
    await update.message.reply_text("📚 *Back to modules:*", parse_mode="Markdown", reply_markup=start_inline_kb(update.effective_user.id))

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admins only."); return
    kb, total = users_list_kb()
    await update.message.reply_text(
        f"👥 *All Users*  _{total} total_\n`{THIN_LINE}`",
        parse_mode="Markdown", reply_markup=kb)

# ── WEB APP DATA ──────────────────────────────────────────────────────────────
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import json
    uid  = update.effective_user.id
    data = update.effective_message.web_app_data.data
    db.upsert_user(update.effective_user)
    try: payload = json.loads(data)
    except Exception: return

    action = payload.get("action")
    if action == "download":
        fid = payload.get("file_id")
        with db.get_conn() as conn:
            f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f:
            await update.message.reply_text("❌ File not found."); return
        await send_db_file(context.bot, update.effective_chat.id, f)
        log_download(uid, update.effective_user.username,
                     update.effective_user.first_name, fid, f["filename"])

    elif action == "getall":
        mid   = payload.get("module_id")
        files = db.get_files(mid)
        if not files:
            await update.message.reply_text("📭 No files in this module."); return
        await update.message.reply_text(f"📤 *Sending {len(files)} file(s)...*", parse_mode="Markdown")
        for f in files:
            await send_db_file(context.bot, update.effective_chat.id, f)
            log_download(uid, update.effective_user.username,
                         update.effective_user.first_name, f["id"], f["filename"])
            await asyncio.sleep(0.35)
        await update.message.reply_text(f"✅ *Done!* {len(files)} file(s) sent.",
            parse_mode="Markdown", reply_markup=after_send_kb(mid))

# ── BUTTON HANDLER ────────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data    = query.data
    uid     = query.from_user.id
    chat_id = query.message.chat_id
    admin   = is_admin(uid)
    db.upsert_user(query.from_user)

    if data == "noop": return

    if data == "home":
        await safe_edit(query, context, chat_id, "📚 *Choose a module:*", reply_markup=start_inline_kb(uid))

    elif data == "help":
        await safe_edit(query, context, chat_id,
            f"ℹ️ *Help*\n`{THIN_LINE}`\n\n"
            "📱 *Open Study App* — full UI inside Telegram\n"
            "📚 Tap a module → see its files\n"
            "📬 *Get ALL Files* → receive everything\n"
            "📄 Tap a file → get just that file\n\n"
            f"*Admin only:*\n`{DIVIDER}`\n"
            "➕ Add · 🗑️ Clear · 👁️ Log · 👥 Users · 📊 Stats\n\n"
            "/manage · /users · /cancel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Open App", web_app=WebAppInfo(url=MINI_APP_URL))],
                [InlineKeyboardButton("🏠  Back",    callback_data="home")]]))

    elif data.startswith("mod:"):
        mid = int(data.split(":")[1]); m = _get_module(mid)
        if not m: await query.answer("❌ Not found.", show_alert=True); return
        count = len(db.get_files(mid)); emoji = module_emoji(m["name"])
        await safe_edit(query, context, chat_id,
            f"{emoji} *{m['name']}*\n`{THIN_LINE}`\n📁  *{count} file(s)*\n\n_Pick a file or get them all:_",
            reply_markup=module_kb(mid, admin))
        context.user_data["last_mod"] = mid

    elif data.startswith("getall:"):
        mid = int(data.split(":")[1]); files = db.get_files(mid)
        if not files:
            await safe_edit(query, context, chat_id, "📭 *No files yet.*", reply_markup=after_send_kb(mid)); return
        await safe_edit(query, context, chat_id, f"📤 *Sending {len(files)} file(s)...*")
        for f in files:
            try:
                await send_db_file(context.bot, chat_id, f)
                log_download(uid, query.from_user.username, query.from_user.first_name, f["id"], f["filename"])
                await asyncio.sleep(0.35)
            except Exception as e: logger.error(f"getall: {e}")
        await context.bot.send_message(chat_id, f"✅ *Done!* {len(files)} file(s) sent.",
            parse_mode="Markdown", reply_markup=after_send_kb(mid))

    elif data.startswith("getfile:"):
        fid = int(data.split(":")[1])
        with db.get_conn() as conn:
            f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f: await query.answer("❌ Not found.", show_alert=True); return
        mid = f["module_id"]
        await safe_edit(query, context, chat_id, f"📬 *Sending:*\n`{f['filename']}`")
        try:
            await send_db_file(context.bot, chat_id, f)
            log_download(uid, query.from_user.username, query.from_user.first_name, fid, f["filename"])
        except Exception as e: logger.error(f"getfile: {e}")
        await context.bot.send_message(chat_id, f"✅ *{f['filename']}* sent!",
            parse_mode="Markdown", reply_markup=after_send_kb(mid))

    elif data.startswith("addfile:"):
        if not admin: await query.answer("⛔ Admins only.", show_alert=True); return
        mid = int(data.split(":")[1])
        context.user_data["upload_mid"] = mid; context.user_data["uploading"] = True
        m = _get_module(mid); emoji = module_emoji(m["name"])
        await safe_edit(query, context, chat_id,
            f"📎 *Upload to:* {emoji} *{m['name']}*\n`{THIN_LINE}`\n\n"
            f"Send any file. _Optional caption:_ `notes` · `exam` · `summary`\n/cancel when done.")

    elif data.startswith("clearmod:"):
        if not admin: await query.answer("⛔ Admins only.", show_alert=True); return
        mid = int(data.split(":")[1])
        with db.get_conn() as conn:
            cnt = conn.execute("SELECT COUNT(*) as c FROM files WHERE module_id=?", (mid,)).fetchone()["c"]
            conn.execute("DELETE FROM files WHERE module_id=?", (mid,))
        await query.answer(f"🗑️ {cnt} file(s) deleted.", show_alert=True)
        m = _get_module(mid); emoji = module_emoji(m["name"])
        await safe_edit(query, context, chat_id, f"{emoji} *{m['name']}*\n`{THIN_LINE}`\n📁 *0 files*",
            reply_markup=module_kb(mid, admin))

    elif data.startswith("dllog:"):
        if not admin: await query.answer("⛔ Admins only.", show_alert=True); return
        mid = int(data.split(":")[1]); logs = get_dl_log(mid)
        m = _get_module(mid); emoji = module_emoji(m["name"])
        if not logs:
            await safe_edit(query, context, chat_id,
                f"👁️ *Download Log*\n{emoji} _{m['name']}_\n`{THIN_LINE}`\n\n_No downloads yet._",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"mod:{mid}")]])); return
        lines = [f"👁️ *Download Log*\n{emoji} _{m['name']}_\n`{THIN_LINE}`\n"]
        for l in logs:
            uname = f"@{l['username']}" if l["username"] else f"#{l['user_id']}"
            lines.append(f"• *{l['first_name']}* {uname}\n  `{l['filename']}`  _{l['downloaded_at']}_")
        text = "\n".join(lines)
        if len(text) > 4000: text = text[:3990] + "\n_…truncated_"
        await safe_edit(query, context, chat_id, text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data=f"mod:{mid}")]]))

    elif data == "admin:panel":
        if not admin: return
        tu, td, top = get_global_stats()
        await safe_edit(query, context, chat_id,
            f"⚙️ *Admin Panel*\n`{THIN_LINE}`\n👥 Users: *{tu}*   📥 Downloads: *{td}*",
            reply_markup=admin_panel_kb())

    elif data == "admin:study":
        if not admin: return
        await safe_edit(query, context, chat_id, f"📚 *Study Files Manager*\n`{THIN_LINE}`\nPick a module:",
            reply_markup=admin_study_kb())

    elif data == "admin:stats":
        if not admin: return
        tu, td, top = get_global_stats()
        top_txt = (f"\n🏆 *Top:* {top[0]}  _{top[1]} dl_") if top else ""
        await safe_edit(query, context, chat_id,
            f"📊 *Global Stats*\n`{THIN_LINE}`\n\n👥 *Users:* {tu}\n📥 *Downloads:* {td}{top_txt}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="admin:panel")]]))

    elif data.startswith("admin:users"):
        if not admin: return
        parts = data.split(":"); page = int(parts[2]) if len(parts)==3 else 0
        kb, total = users_list_kb(page)
        await safe_edit(query, context, chat_id, f"👥 *All Users*  _{total} total_\n`{THIN_LINE}`", reply_markup=kb)

    elif data.startswith("admin:user:"):
        if not admin: return
        target_uid = int(data.split(":")[2]); logs = get_user_activity(target_uid)
        with db.get_conn() as c:
            u = c.execute("SELECT * FROM users WHERE user_id=?", (target_uid,)).fetchone()
        name = u["first_name"] if u else "?"
        uname = f"@{u['username']}" if u and u.get("username") else f"#{target_uid}"
        if not logs:
            text = f"👤 *{name}*  {uname}\n`{THIN_LINE}`\n\n_No downloads yet._"
        else:
            lines = [f"👤 *{name}*  {uname}\n`{THIN_LINE}`\n"]
            for l in logs: lines.append(f"• `{l['filename']}`\n  _{l['downloaded_at']}_")
            text = "\n".join(lines)
            if len(text) > 4000: text = text[:3990] + "\n_…truncated_"
        await safe_edit(query, context, chat_id, text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="admin:users:0")]]))

    elif data.startswith("adm:mod:"):
        if not admin: return
        mid = int(data.split(":")[2]); m = _get_module(mid)
        if not m: await query.answer("❌ Not found.", show_alert=True); return
        emoji = module_emoji(m["name"]); count = len(db.get_files(mid))
        await safe_edit(query, context, chat_id,
            f"{emoji} *{m['name']}*\n`{THIN_LINE}`\n📁 *{count} file(s)*",
            reply_markup=admin_module_kb(mid))

    elif data.startswith("adm:add:"):
        if not admin: return
        mid = int(data.split(":")[2])
        context.user_data["upload_mid"] = mid; context.user_data["uploading"] = True
        m = _get_module(mid); emoji = module_emoji(m["name"])
        await safe_edit(query, context, chat_id,
            f"📎 *Upload to:* {emoji} *{m['name']}*\n`{THIN_LINE}`\n\n"
            f"Send any file. _Optional caption:_ `notes` · `exam` · `summary`\n/cancel when done.")

    elif data.startswith("adm:del:"):
        if not admin: return
        parts = data.split(":"); fid = int(parts[2]); mid = int(parts[3])
        with db.get_conn() as conn:
            row = conn.execute("SELECT filename FROM files WHERE id=?", (fid,)).fetchone()
            conn.execute("DELETE FROM files WHERE id=?", (fid,))
        fname = row["filename"] if row else "file"
        await query.answer(f"🗑 '{fname}' deleted.")
        m = _get_module(mid); emoji = module_emoji(m["name"]); count = len(db.get_files(mid))
        await safe_edit(query, context, chat_id,
            f"{emoji} *{m['name']}*\n`{THIN_LINE}`\n📁 *{count} file(s)*",
            reply_markup=admin_module_kb(mid))

    elif data.startswith("adm:clear:"):
        if not admin: return
        mid = int(data.split(":")[2])
        with db.get_conn() as conn:
            cnt = conn.execute("SELECT COUNT(*) as c FROM files WHERE module_id=?", (mid,)).fetchone()["c"]
            conn.execute("DELETE FROM files WHERE module_id=?", (mid,))
        await query.answer(f"🗑️ {cnt} file(s) deleted.", show_alert=True)
        m = _get_module(mid); emoji = module_emoji(m["name"])
        await safe_edit(query, context, chat_id,
            f"{emoji} *{m['name']}*\n`{THIN_LINE}`\n📁 *0 files*",
            reply_markup=admin_module_kb(mid))

# ── FILE UPLOAD HANDLER ───────────────────────────────────────────────────────
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    msg     = update.message
    caption = (msg.caption or "").strip()
    db.upsert_user(update.effective_user)

    if not (is_admin(uid) and context.user_data.get("uploading")): return
    mid = context.user_data.get("upload_mid")
    if not mid:
        await msg.reply_text("⚠️ No module selected. Use /manage."); return

    file_id = ftype = file_name = None
    if msg.audio:
        file_id = msg.audio.file_id; file_name = msg.audio.file_name or msg.audio.title or "Audio"; ftype = "audio"
    elif msg.voice:
        file_id = msg.voice.file_id; file_name = f"Voice_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"; ftype = "audio"
    elif msg.video:
        file_id = msg.video.file_id; file_name = msg.video.file_name or "Video"; ftype = "video"
    elif msg.video_note:
        file_id = msg.video_note.file_id; file_name = f"VideoNote_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"; ftype = "video"
    elif msg.document:
        file_id = msg.document.file_id; file_name = msg.document.file_name or "Document"
        ext = file_name.rsplit(".",1)[-1].lower() if "." in file_name else ""
        if   ext in {"mp3","flac","wav","ogg","opus","m4a","aac"}: ftype = "audio"
        elif ext in {"mp4","mkv","avi","mov","wmv","webm"}:        ftype = "video"
        else:                                                       ftype = "document"
    elif msg.photo:
        file_id = msg.photo[-1].file_id; ftype = "photo"
        file_name = (caption if caption and caption not in {"notes","exam","summary"}
                     else f"Photo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")

    if not file_id: return
    tag     = caption if caption in {"notes","exam","summary"} else "notes"
    display = file_name if ftype == "document" else (clean_filename(file_name) or file_name)
    db.add_file(mid, file_id, display, ftype, tag)
    count = len(db.get_files(mid))
    icon  = {"audio":"🎵","video":"🎬","photo":"🖼️"}.get(ftype,"📄")
    m     = _get_module(mid); emoji = module_emoji(m["name"])
    await msg.reply_text(
        f"{icon} *Saved:* `{display}`\n🏷️ Tag: `{tag}`\n`{THIN_LINE}`\n"
        f"{emoji} _{m['name']}_ · *{count} file(s)* total\n\n_Send another or_ /cancel _when done._",
        parse_mode="Markdown")

# ── SET COMMANDS ──────────────────────────────────────────────────────────────
async def set_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start",  "📱 Open Study App"),
        BotCommand("manage", "⚙️ Admin: manage study files"),
        BotCommand("users",  "👥 Admin: view all users"),
        BotCommand("cancel", "❌ Cancel current upload"),
    ])
    logger.info("✅ Commands set")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    db.init_db()
    with db.get_conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS file_downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, first_name TEXT,
            file_db_id INTEGER, filename TEXT, downloaded_at TEXT)""")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("manage", manage_cmd))
    app.add_handler(CommandHandler("users",  users_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.AUDIO | filters.VIDEO |
        filters.VOICE | filters.VIDEO_NOTE | filters.PHOTO, handle_file))
    app.post_init = set_commands
    logger.info("🚀 Elite Life Bot + Mini App started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
