import re
import os
import sqlite3
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ChatAction
from telegram.ext import (
    CallbackQueryHandler,
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv(".env", override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DAHL_API_KEY = os.getenv("DAHL_API_KEY", "")
DAHL_MODEL = os.getenv("DAHL_MODEL", "MiniMaxAI/MiniMax-M2.7")

DB = "ramain_ai.db"

client = OpenAI(
    api_key=DAHL_API_KEY,
    base_url="https://inference.dahl.global/v1",
)


# =========================
# DATABASE
# =========================

def db():
    return sqlite3.connect(DB)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT,
            last_seen TEXT,
            requests INTEGER DEFAULT 0,
            blocked INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    con.commit()
    con.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_user(user):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        now(),
        now(),
    ))

    cur.execute("""
        UPDATE users
        SET username=?, first_name=?, last_seen=?
        WHERE user_id=?
    """, (
        user.username or "",
        user.first_name or "",
        now(),
        user.id,
    ))

    con.commit()
    con.close()


def is_blocked(user_id):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT blocked FROM users WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()
    con.close()

    return bool(row and row[0])


def add_message(user_id, role, content):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO messages
        (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        role,
        content,
        now(),
    ))

    con.commit()
    con.close()


def get_history(user_id, limit=16):
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT role, content
        FROM messages
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))

    rows = cur.fetchall()
    con.close()

    rows.reverse()

    return [
        {"role": role, "content": content}
        for role, content in rows
    ]


def clear_history(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM messages WHERE user_id=?",
        (user_id,)
    )

    con.commit()
    con.close()


def increase_requests(user_id):
    con = db()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET requests=requests+1
        WHERE user_id=?
    """, (user_id,))

    con.commit()
    con.close()


def set_block(user_id, value):
    con = db()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET blocked=?
        WHERE user_id=?
    """, (value, user_id))

    con.commit()
    con.close()


# =========================
# KEYBOARDS
# =========================

def main_keyboard(user_id=None):
    rows = [
        [
            KeyboardButton("🤖 چت با Ramin AI"),
            KeyboardButton("🧠 حافظه چت"),
        ],
        [
            KeyboardButton("💻 کمک برنامه‌نویسی"),
            KeyboardButton("✍️ اصلاح متن"),
        ],
        [
            KeyboardButton("🔢 حل ریاضی"),
            KeyboardButton("📊 آمار مصرف"),
        ],
        [
            KeyboardButton("🗑 پاک کردن حافظه"),
            KeyboardButton("ℹ️ درباره Ramin AI"),
        ],
        [
            KeyboardButton("🏠 منوی اصلی"),
        ],
    ]

    if user_id == ADMIN_ID:
        rows.append([
            KeyboardButton("👑 پنل مدیریت")
        ])

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
    )


def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("👥 کاربران"),
                KeyboardButton("📊 آمار کل"),
            ],
            [
                KeyboardButton("🚫 مسدود کردن"),
                KeyboardButton("✅ آزاد کردن"),
            ],
            [
                KeyboardButton("📢 پیام همگانی"),
                KeyboardButton("🤖 مدل فعلی"),
            ],
            [
                KeyboardButton("💬 پیام‌های کاربران"),
            ],
            [
                KeyboardButton("🏠 منوی اصلی"),
            ],
        ],
        resize_keyboard=True,
    )


# =========================
# AI
# =========================

SYSTEM_PROMPT = """
You are Ramin AI, a helpful, friendly and natural Persian AI assistant.

Your personality:
- Talk to the user like a friendly, respectful and approachable friend.
- When the user writes Persian, reply in fluent, natural Persian.
- Prefer a warm, conversational and slightly casual tone instead of a formal, robotic or textbook-like tone.
- Be friendly without being overly silly, childish, or repetitive.
- Don't constantly use phrases like "حتماً دوست عزیز" or "باعث افتخار من است".
- Adapt your tone to the user's mood and the subject.
- If the user asks something simple, answer simply. Don't make short questions unnecessarily long.

Answer style:
- Keep answers clear, useful and easy to read.
- Avoid excessive Markdown formatting.
- Do not use unnecessary # or ## headings.
- Avoid large blocks of Markdown such as $$...$$ when a simpler readable format is possible.
- Use short paragraphs and natural spacing.
- For math, programming or educational questions, explain step by step when useful.
- Use emojis naturally and sparingly when they improve readability.
- Don't make every answer look like an article or formal documentation.
- If the user makes a mistake, correct them politely and naturally without sounding judgmental.
- Never claim abilities or actions you do not actually have.
- For programming questions, provide practical and clean code.
- Match the answer length to the user's request. For long or detailed questions, provide a complete answer without unnecessarily shortening it.

Most importantly, sound like a real helpful friend who knows what they are talking about, not like a formal textbook or robotic assistant.
"""


async def ask_ai(user_id, text, mode="chat"):

    history = get_history(user_id)

    extra = ""

    if mode == "code":
        extra = """
The user wants programming help.
Give technically accurate code and explain the important parts.
"""

    elif mode == "rewrite":
        extra = """
The user wants text editing.
Rewrite or improve the text while preserving its intended meaning.
"""

    elif mode == "math":
        extra = """
The user wants mathematics help.
Solve step by step and give the final answer clearly.
"""

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + extra,
        }
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": text,
    })

    def request():
        return client.chat.completions.create(
            model=DAHL_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=700,
        )

    response = await asyncio.to_thread(request)

    answer = response.choices[0].message.content
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL | re.IGNORECASE).strip()
    answer = re.sub(r"<think>.*$", "", answer, flags=re.DOTALL | re.IGNORECASE).strip()

    if not answer:
        answer = "پاسخی از مدل دریافت نشد."

    add_message(user_id, "user", text)
    add_message(user_id, "assistant", answer)
    increase_requests(user_id)

    return answer


# =========================
# COMMANDS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    register_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "⛔ دسترسی شما به Ramin AI مسدود شده است."
        )
        return

    await update.message.reply_text(
        f"سلام {user.first_name or 'دوست من'} 👋\n\n"
        "به Ramin AI خوش اومدی 🤖\n"
        "من آماده‌ام به سوالاتت جواب بدم.",
        reply_markup=main_keyboard(user.id),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return

    await update.message.reply_text(
        "🛠 پنل مدیریت Ramin AI",
        reply_markup=admin_keyboard(),
    )


# =========================
# ADMIN STATS
# =========================

def get_stats():
    con = db()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE blocked=1")
    blocked = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(requests),0) FROM users")
    requests = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM messages")
    messages = cur.fetchone()[0]

    con.close()

    return users, blocked, requests, messages



# =========================
# ADMIN USER MESSAGES
# =========================

def get_user_messages_page(page=0, per_page=10):
    con = db()
    cur = con.cursor()

    offset = page * per_page

    cur.execute("""
        SELECT user_id, role, content, created_at
        FROM messages
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))

    rows = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM messages")
    total = cur.fetchone()[0]

    con.close()

    return rows, total


def format_user_messages(page=0):
    rows, total = get_user_messages_page(page)

    per_page = 10
    total_pages = max(1, (total + per_page - 1) // per_page)

    text = (
        f"💬 پیام‌های کاربران\n"
        f"📄 صفحه {page + 1} از {total_pages}\n"
        f"━━━━━━━━━━━━━━\n"
    )

    con = db()
    cur = con.cursor()

    for row in rows:
        user_id, role, content, created_at = row

        cur.execute(
            "SELECT username, first_name FROM users WHERE user_id=?",
            (user_id,)
        )
        user = cur.fetchone()

        username = user[0] if user and user[0] else None
        first_name = user[1] if user and user[1] else "بدون نام"

        if username:
            user_display = f"@{username}"
        else:
            user_display = first_name

        role_name = "👤 کاربر" if role == "user" else "🤖 Ramin AI"

        text += (
            f"\n{role_name}\n"
            f"👤 {user_display}\n"
            f"🆔 {user_id}\n"
            f"🕐 {created_at}\n"
            f"💬 {content}\n"
            f"━━━━━━━━━━━━━━\n"
        )

    con.close()

    return text, total_pages

async def show_user_messages(update, context, page=0):
    if update.effective_user.id != ADMIN_ID:
        return

    text, total_pages = format_user_messages(page)

    buttons = []

    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=f"user_messages:{page - 1}"
            )
        )

    if total_pages and page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(
                "بعدی ➡️",
                callback_data=f"user_messages:{page + 1}"
            )
        )

    keyboard = [buttons] if buttons else []

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=markup
        )


async def user_messages_callback(update, context):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    try:
        page = int(query.data.split(":")[1])
    except:
        page = 0

    await show_user_messages(update, context, page)


# =========================
# TEXT HANDLER
# =========================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    text = (update.message.text or "").strip()

    register_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "⛔ دسترسی شما به Ramin AI مسدود شده است."
        )
        return

    # ADMIN
    if user.id == ADMIN_ID:

        if text == "👥 کاربران":
            users, blocked, requests, messages = get_stats()

            await update.message.reply_text(
                f"👥 کاربران: {users}\n"
                f"🚫 مسدود: {blocked}\n"
                f"🤖 درخواست‌ها: {requests}\n"
                f"💬 پیام‌ها: {messages}"
            )
            return

        if text == "📊 آمار کل":
            users, blocked, requests, messages = get_stats()

            await update.message.reply_text(
                "📊 آمار Ramin AI\n\n"
                f"👥 کاربران: {users}\n"
                f"🚫 مسدود شده: {blocked}\n"
                f"🤖 درخواست AI: {requests}\n"
                f"💬 کل پیام‌ها: {messages}"
            )
            return

        if text == "🤖 مدل فعلی":
            await update.message.reply_text(
                f"🤖 مدل فعلی:\n\n{DAHL_MODEL}"
            )
            return

        if text == "🚫 مسدود کردن":
            context.user_data["admin_action"] = "block"
            await update.message.reply_text(
                "آیدی عددی کاربر را ارسال کن:"
            )
            return

        if text == "✅ آزاد کردن":
            context.user_data["admin_action"] = "unblock"
            await update.message.reply_text(
                "آیدی عددی کاربر را ارسال کن:"
            )
            return

        if text == "📢 پیام همگانی":
            context.user_data["admin_action"] = "broadcast"
            await update.message.reply_text(
                "متن پیام همگانی را ارسال کن:"
            )
            return

        if text == "🏠 منوی اصلی":
            await update.message.reply_text(
                "🏠 منوی اصلی",
                reply_markup=main_keyboard(),
            )
            return

        action = context.user_data.get("admin_action")

        if action == "block":
            try:
                uid = int(text)
                set_block(uid, 1)

                context.user_data.pop("admin_action", None)

                await update.message.reply_text(
                    f"🚫 کاربر {uid} مسدود شد."
                )
            except:
                await update.message.reply_text(
                    "❌ آیدی نامعتبر است."
                )
            return

        if action == "unblock":
            try:
                uid = int(text)
                set_block(uid, 0)

                context.user_data.pop("admin_action", None)

                await update.message.reply_text(
                    f"✅ کاربر {uid} آزاد شد."
                )
            except:
                await update.message.reply_text(
                    "❌ آیدی نامعتبر است."
                )
            return

        if action == "broadcast":
            con = db()
            cur = con.cursor()

            cur.execute(
                "SELECT user_id FROM users WHERE blocked=0"
            )

            ids = [x[0] for x in cur.fetchall()]
            con.close()

            context.user_data.pop("admin_action", None)

            sent = 0

            for uid in ids:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=text,
                    )
                    sent += 1
                    await asyncio.sleep(0.05)
                except:
                    pass

            await update.message.reply_text(
                f"📢 ارسال انجام شد.\n"
                f"تعداد موفق: {sent}"
            )
            return

    # ADMIN USER MESSAGES

    if user.id == ADMIN_ID and text == "💬 پیام‌های کاربران":
        await show_user_messages(update, context, 0)
        return

    # USER MENU

    if text == "🤖 چت با Ramin AI":
        await update.message.reply_text(
            "🤖 سوالت رو بفرست."
        )
        context.user_data["mode"] = "chat"
        return

    if text == "🧠 حافظه چت":
        history = get_history(user.id)

        await update.message.reply_text(
            f"🧠 حافظه چت\n\n"
            f"تعداد پیام‌های ذخیره‌شده: {len(history)}\n\n"
            "Ramin AI از پیام‌های اخیر مکالمه برای حفظ context استفاده می‌کند."
        )
        return

    if text == "🗑 پاک کردن حافظه":
        clear_history(user.id)

        await update.message.reply_text(
            "✅ حافظه مکالمه پاک شد."
        )
        return

    if text == "💻 کمک برنامه‌نویسی":
        context.user_data["mode"] = "code"

        await update.message.reply_text(
            "💻 حالت برنامه‌نویسی فعال شد.\n"
            "سوال یا کدت رو بفرست."
        )
        return

    if text == "✍️ اصلاح متن":
        context.user_data["mode"] = "rewrite"

        await update.message.reply_text(
            "✍️ متن موردنظرت رو بفرست."
        )
        return

    if text == "🔢 حل ریاضی":
        context.user_data["mode"] = "math"

        await update.message.reply_text(
            "🔢 مسئله ریاضی رو بفرست."
        )
        return

    if text == "📊 آمار مصرف":
        con = db()
        cur = con.cursor()

        cur.execute(
            "SELECT requests FROM users WHERE user_id=?",
            (user.id,)
        )

        row = cur.fetchone()
        con.close()

        requests = row[0] if row else 0

        await update.message.reply_text(
            f"📊 آمار مصرف شما\n\n"
            f"🤖 درخواست‌های AI: {requests}"
        )
        return

    if text == "ℹ️ درباره Ramin AI":
        await update.message.reply_text(
            "🤖 Ramin AI\n\n"
            "دستیار هوش مصنوعی فارسی\n"
            "ساخته‌شده برای چت، برنامه‌نویسی، اصلاح متن و ریاضی."
        )
        return

    # AI REQUEST

    mode = context.user_data.get("mode", "chat")

    # پیام لودینگ متحرک
    loading_frames = [
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠼",
        "⠴",
        "⠦",
        "⠧",
        "⠇",
        "⠏",
    ]

    wait_message = await update.message.reply_text(
        loading_frames[0],
        reply_to_message_id=update.message.message_id
    )

    async def animate_loading():
        index = 0

        try:
            while True:
                await asyncio.sleep(0.25)
                index = (index + 1) % len(loading_frames)

                await wait_message.edit_text(
                    loading_frames[index]
                )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print("LOADING ANIMATION ERROR:", repr(e))

    loading_task = asyncio.create_task(
        animate_loading()
    )

    await update.message.chat.send_action(
        ChatAction.TYPING
    )

    try:
        answer = await ask_ai(
            user.id,
            text,
            mode,
        )

        loading_task.cancel()
        await asyncio.gather(
            loading_task,
            return_exceptions=True,
        )

        # Telegram message limit
        if len(answer) <= 4000:
            await wait_message.edit_text(answer)
        else:
            # اولین بخش جایگزین پیام Wait می‌شود
            await wait_message.edit_text(answer[:4000])

            # ادامه پاسخ در پیام‌های بعدی
            for i in range(4000, len(answer), 4000):
                await update.message.reply_text(
                    answer[i:i+4000]
                )

    except Exception as e:

        print("AI ERROR:", repr(e))

        await wait_message.edit_text(
            "❌ خطا در ارتباط با سرویس هوش مصنوعی.\n"
            "چند لحظه بعد دوباره امتحان کن."
        )


# =========================
# ERROR
# =========================

async def error_handler(update, context):
    print("BOT ERROR:", repr(context.error))



