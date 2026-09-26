import os
import re
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime

import edge_tts
import speech_recognition as sr
from pydub import AudioSegment
from dotenv import load_dotenv

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8394607974"))
CHANNEL = os.getenv("CHANNEL", "@ByteTunnel").strip()

DB_FILE = "bytevoice.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN در فایل .env تنظیم نشده است.")


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    is_blocked INTEGER DEFAULT 0,
    created_at TEXT,
    last_seen TEXT
)
""")

db.commit()


def add_or_update_user(user):
    now = datetime.now().isoformat(timespec="seconds")

    db.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            is_blocked,
            created_at,
            last_seen
        )
        VALUES (?, ?, ?, 0, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_seen = excluded.last_seen
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        now,
        now,
    ))

    db.commit()


def is_blocked(user_id):
    row = db.execute(
        "SELECT is_blocked FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    return bool(row and row["is_blocked"])


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🎙️ تبدیل متن به ویس"],
            ["📝 تبدیل صدا به متن"],
            ["🎚️ انتخاب صدا", "ℹ️ راهنما"],
            ["🏠 منوی اصلی"],
        ],
        resize_keyboard=True
    )


def voice_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🇮🇷 فارسی", "🇺🇸 انگلیسی"],
            ["🌍 صداهای بیشتر"],
            ["🏠 منوی اصلی"],
        ],
        resize_keyboard=True
    )


# =========================================================
# VOICES
# =========================================================

VOICES = {
    "fa": {
        "name": "🇮🇷 فارسی",
        "voice": "fa-IR-DilaraNeural",
    },
    "en": {
        "name": "🇺🇸 انگلیسی",
        "voice": "en-US-JennyNeural",
    },
    "en_male": {
        "name": "🇺🇸 انگلیسی مردانه",
        "voice": "en-US-GuyNeural",
    },
    "fa_male": {
        "name": "🇮🇷 فارسی مردانه",
        "voice": "fa-IR-FaridNeural",
    },
    "ar": {
        "name": "🇸🇦 عربی",
        "voice": "ar-SA-ZariyahNeural",
    },
    "tr": {
        "name": "🇹🇷 ترکی",
        "voice": "tr-TR-EmelNeural",
    },
    "de": {
        "name": "🇩🇪 آلمانی",
        "voice": "de-DE-KatjaNeural",
    },
    "fr": {
        "name": "🇫🇷 فرانسوی",
        "voice": "fr-FR-DeniseNeural",
    },
    "ru": {
        "name": "🇷🇺 روسی",
        "voice": "ru-RU-SvetlanaNeural",
    },
}


# انتخاب صدای پیش‌فرض هر کاربر
user_voices = {}


def get_user_voice(user_id):
    return user_voices.get(user_id, "fa")


def contains_persian(text):
    return bool(re.search(r"[\u0600-\u06FF]", text))


def detect_language(text):
    """
    تشخیص ساده زبان.
    اگر حروف فارسی/عربی وجود داشته باشد، فارسی در نظر گرفته می‌شود.
    برای متن لاتین، چند الگوی ساده بررسی می‌شود.
    """

    if contains_persian(text):
        return "fa"

    lower = text.lower()

    # ترکی
    if any(x in lower for x in ["ş", "ğ", "ı", "ç", "ö", "ü"]):
        return "tr"

    # روسی
    if re.search(r"[а-яё]", lower):
        return "ru"

    # آلمانی
    if any(x in lower for x in [" der ", " die ", " das ", " und ", " nicht "]):
        return "de"

    # فرانسوی
    if any(x in lower for x in [" le ", " la ", " les ", " des ", " une ", " est "]):
        return "fr"

    # عربی بدون حروف فارسی
    if re.search(r"[\u0621-\u064A]", text):
        return "ar"

    return "en"


# =========================================================
# MEMBERSHIP
# =========================================================

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)

        return member.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ]

    except Exception as e:
        print("Membership check error:", e)
        return False


async def check_membership(update):
    user = update.effective_user

    if await is_member(update.get_bot(), user.id):
        return True

    await update.message.reply_text(
        "🔒 برای استفاده از بات ابتدا باید عضو کانال ما بشی.\n\n"
        "📢 کانال: @ByteTunnel\n\n"
        "بعد از عضویت دوباره روی «🎙️ تبدیل متن به ویس» بزن.",
        reply_markup=main_keyboard()
    )

    return False


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    add_or_update_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 دسترسی شما به این بات مسدود شده است."
        )
        return

    if not await check_membership(update):
        return

    await update.message.reply_text(
        "🎙️ به ByteVoiceBot خوش اومدی!\n\n"
        "📝 هر متنی که بفرستی می‌تونم به صدا تبدیلش کنم.\n\n"
        "🇮🇷 فارسی\n"
        "🇺🇸 انگلیسی\n"
        "🌍 و چندین زبان دیگر\n\n"
        "برای شروع روی «🎙️ تبدیل متن به ویس» بزن.",
        reply_markup=main_keyboard()
    )


# =========================================================
# HELP
# =========================================================

async def help_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update):
        return

    await update.message.reply_text(
        "ℹ️ راهنمای ByteVoiceBot\n\n"
        "1️⃣ روی «🎙️ تبدیل متن به ویس» بزن.\n"
        "2️⃣ متن خودت رو ارسال کن.\n"
        "3️⃣ بات زبان متن رو تشخیص می‌ده.\n"
        "4️⃣ متن به فایل صوتی تبدیل می‌شه.\n"
        "5️⃣ ویس برات ارسال می‌شه.\n\n"
        "💡 می‌تونی فارسی، انگلیسی و چند زبان دیگه رو امتحان کنی.",
        reply_markup=main_keyboard()
    )


# =========================================================
# VOICE MENU
# =========================================================

async def voice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update):
        return

    await update.message.reply_text(
        "🎙️ بخش تبدیل متن به ویس\n\n"
        "زبان یا صدای موردنظر خودت رو انتخاب کن، "
        "یا مستقیماً متنت رو بفرست تا زبانش تشخیص داده بشه.",
        reply_markup=voice_keyboard()
    )


async def more_voices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update):
        return

    keyboard = ReplyKeyboardMarkup(
        [
            ["🇮🇷 فارسی زن", "🇮🇷 فارسی مرد"],
            ["🇺🇸 انگلیسی زن", "🇺🇸 انگلیسی مرد"],
            ["🇸🇦 عربی", "🇹🇷 ترکی"],
            ["🇩🇪 آلمانی", "🇫🇷 فرانسوی"],
            ["🇷🇺 روسی"],
            ["🏠 منوی اصلی"],
        ],
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🎚️ صدا را انتخاب کن:",
        reply_markup=keyboard
    )


async def select_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update):
        return

    text = update.message.text
    user_id = update.effective_user.id

    mapping = {
        "🇮🇷 فارسی": "fa",
        "🇮🇷 فارسی زن": "fa",
        "🇮🇷 فارسی مرد": "fa_male",
        "🇺🇸 انگلیسی": "en",
        "🇺🇸 انگلیسی زن": "en",
        "🇺🇸 انگلیسی مرد": "en_male",
        "🇸🇦 عربی": "ar",
        "🇹🇷 ترکی": "tr",
        "🇩🇪 آلمانی": "de",
        "🇫🇷 فرانسوی": "fr",
        "🇷🇺 روسی": "ru",
    }

    if text not in mapping:
        return False

    key = mapping[text]
    user_voices[user_id] = key

    language_messages = {
        "fa": "🇮🇷 زبان فارسی انتخاب شد.\n\n📝 لطفاً متن خودت رو به زبان فارسی بفرست تا با صدای فارسی برات بخونم.",
        "fa_male": "🇮🇷 صدای مرد فارسی انتخاب شد.\n\n📝 لطفاً متن خودت رو به زبان فارسی بفرست تا با صدای مرد فارسی برات بخونم.",
        "en": "🇺🇸 English voice selected.\n\n📝 Please send your text in English so I can convert it to speech.",
        "en_male": "🇺🇸 English male voice selected.\n\n📝 Please send your text in English to convert it to speech.",
        "ar": "🇸🇦 تم اختيار الصوت العربي.\n\n📝 يرجى إرسال النص باللغة العربية لتحويله إلى صوت.",
        "tr": "🇹🇷 Türkçe sesi seçildi.\n\n📝 Lütfen seslendirmek istediğiniz metni Türkçe olarak gönderin.",
        "de": "🇩🇪 Deutsche Stimme ausgewählt.\n\n📝 Bitte sende deinen Text auf Deutsch, damit ich ihn in Sprache umwandeln kann.",
        "fr": "🇫🇷 Voix française sélectionnée.\n\n📝 Envoyez votre texte en français pour le convertir en audio.",
        "ru": "🇷🇺 Выбран русский голос.\n\n📝 Пожалуйста, отправьте текст на русском языке, чтобы я мог преобразовать его в аудио.",
    }

    await update.message.reply_text(
        f"✅ صدا تغییر کرد.\n\n"
        f"🎙️ صدا: {VOICES[key]['name']}\n\n"
        f"{language_messages.get(key, '📝 حالا متن خودت رو بفرست.')}",
        reply_markup=main_keyboard()
    )

    return True


# =========================================================
# TEXT TO SPEECH
# =========================================================

async def create_voice(text, voice, output_file):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz",
    )

    await communicate.save(output_file)


async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    add_or_update_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 دسترسی شما به این بات مسدود شده است."
        )
        return

    if not await check_membership(update):
        return

    # دکمه‌های مدیریتی/منو
    if text in [
        "🎙️ تبدیل متن به ویس",
        "🎚️ انتخاب صدا",
        "🌍 صداهای بیشتر",
        "🇮🇷 فارسی",
        "🇺🇸 انگلیسی",
        "🏠 منوی اصلی",
        "ℹ️ راهنما",
        "🇮🇷 فارسی زن",
        "🇮🇷 فارسی مرد",
        "🇺🇸 انگلیسی زن",
        "🇺🇸 انگلیسی مرد",
        "🇸🇦 عربی",
        "🇹🇷 ترکی",
        "🇩🇪 آلمانی",
        "🇫🇷 فرانسوی",
        "🇷🇺 روسی",
    ]:
        return

    # محدودیت منطقی برای جلوگیری از متن بسیار بزرگ
    if len(text) > 5000:
        await update.message.reply_text(
            "⚠️ متن خیلی طولانیه.\n\n"
            "لطفاً متن رو در چند پیام جداگانه ارسال کن.\n"
            "حداکثر هر پیام: ۵۰۰۰ کاراکتر"
        )
        return

    if not text:
        return

    detected = detect_language(text)
    selected_voice = get_user_voice(user.id)

    # اگر کاربر صدای دستی انتخاب نکرده، زبان متن تعیین می‌کند
    if user.id not in user_voices:
        selected_voice = detected

    if selected_voice not in VOICES:
        selected_voice = "en"

    voice_name = VOICES[selected_voice]["name"]
    voice_id = VOICES[selected_voice]["voice"]

    status_message = await update.message.reply_text(
        "⏳ درحال تبدیل متن به ویس...\n\n"
        f"🎙️ صدا: {voice_name}\n"
        "لطفاً چند لحظه صبر کن."
    )

    output_file = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
        ) as temp:
            output_file = temp.name

        await create_voice(
            text,
            voice_id,
            output_file
        )

        await status_message.edit_text(
            "✅ تبدیل انجام شد!\n\n"
            "🎧 درحال ارسال ویس..."
        )

        with open(output_file, "rb") as audio:
            await update.message.reply_audio(
                audio=audio,
                title="ByteVoice",
                performer="ByteVoiceBot",
                caption=text
            )

        await status_message.delete()

    except Exception as e:
        print("TTS ERROR:", repr(e))

        await status_message.edit_text(
            "❌ تبدیل متن به صدا انجام نشد.\n\n"
            "لطفاً دوباره امتحان کن."
        )

    finally:
        if output_file:
            try:
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass


# =========================================================
# ADMIN
# =========================================================

def admin_only(user_id):
    return user_id == ADMIN_ID


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return

    count = db.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    blocked = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE is_blocked = 1"
    ).fetchone()["c"]

    await update.message.reply_text(
        "🛠 پنل مدیریت ByteVoiceBot\n\n"
        f"👥 کل کاربران: {count}\n"
        f"🚫 مسدود شده: {blocked}\n\n"
        "دستورات:\n"
        "/stats - آمار\n"
        "/broadcast متن - ارسال همگانی\n"
        "/block ID - مسدود کردن\n"
        "/unblock ID - رفع مسدودی\n"
        "/users - لیست کاربران"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return

    total = db.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    blocked = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE is_blocked = 1"
    ).fetchone()["c"]

    await update.message.reply_text(
        "📊 آمار ByteVoiceBot\n\n"
        f"👥 کاربران: {total}\n"
        f"🚫 مسدود: {blocked}"
    )


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "استفاده:\n/block USER_ID"
        )
        return

    try:
        user_id = int(context.args[0])

        db.execute(
            "UPDATE users SET is_blocked = 1 WHERE user_id = ?",
            (user_id,)
        )
        db.commit()

        await update.message.reply_text(
            f"🚫 کاربر {user_id} مسدود شد."
        )

    except ValueError:
        await update.message.reply_text(
            "❌ آیدی نامعتبر است."
        )


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "استفاده:\n/unblock USER_ID"
        )
        return

    try:
        user_id = int(context.args[0])

        db.execute(
            "UPDATE users SET is_blocked = 0 WHERE user_id = ?",
            (user_id,)
        )
        db.commit()

        await update.message.reply_text(
            f"✅ کاربر {user_id} رفع مسدودی شد."
        )

    except ValueError:
        await update.message.reply_text(
            "❌ آیدی نامعتبر است."
        )


async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return

    rows = db.execute("""
        SELECT user_id, username, first_name, is_blocked
        FROM users
        ORDER BY last_seen DESC
        LIMIT 30
    """).fetchall()

    if not rows:
        await update.message.reply_text(
            "هنوز کاربری ثبت نشده."
        )
        return

    lines = ["👥 آخرین کاربران:\n"]

    for row in rows:
        status = "🚫" if row["is_blocked"] else "✅"

        name = row["first_name"] or "-"
        username = (
            f"@{row['username']}"
            if row["username"]
            else "-"
        )

        lines.append(
            f"{status} {name} | {username}\n"
            f"ID: {row['user_id']}"
        )

    await update.message.reply_text(
        "\n\n".join(lines)
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "استفاده:\n/broadcast متن پیام"
        )
        return

    message = " ".join(context.args)

    rows = db.execute("""
        SELECT user_id
        FROM users
        WHERE is_blocked = 0
    """).fetchall()

    success = 0
    failed = 0

    status = await update.message.reply_text(
        "📢 ارسال همگانی شروع شد..."
    )

    for row in rows:
        user_id = row["user_id"]

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message
            )

            success += 1

            await asyncio.sleep(0.05)

        except Exception as e:
            print(
                "Broadcast error:",
                user_id,
                repr(e)
            )
            failed += 1

    await status.edit_text(
        "📢 ارسال همگانی تمام شد.\n\n"
        f"✅ موفق: {success}\n"
        f"❌ ناموفق: {failed}"
    )


# =========================================================
# BUTTON ROUTER
# =========================================================

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🎙️ تبدیل متن به ویس":
        await voice_menu(update, context)
        return

    if text == "📝 تبدیل صدا به متن":
        await update.message.reply_text(
            "📝 لطفاً ویس یا فایل صوتی خودت رو بفرست.\n\n"
            "🎧 فعلاً تشخیص گفتار روی زبان فارسی تنظیم شده.",
            reply_markup=main_keyboard()
        )
        return

    if text == "🎚️ انتخاب صدا":
        await more_voices(update, context)
        return

    if text == "🌍 صداهای بیشتر":
        await more_voices(update, context)
        return

    if text == "ℹ️ راهنما":
        await help_message(update, context)
        return

    if text == "🏠 منوی اصلی":
        await start(update, context)
        return

    if text in [
        "🇮🇷 فارسی",
        "🇺🇸 انگلیسی",
        "🇮🇷 فارسی زن",
        "🇮🇷 فارسی مرد",
        "🇺🇸 انگلیسی زن",
        "🇺🇸 انگلیسی مرد",
        "🇸🇦 عربی",
        "🇹🇷 ترکی",
        "🇩🇪 آلمانی",
        "🇫🇷 فرانسوی",
        "🇷🇺 روسی",
    ]:
        await select_voice(update, context)
        return

    await text_to_speech(update, context)



# =========================================================
# VOICE TO TEXT
# =========================================================

async def voice_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not (message.voice or message.audio):
        return

    status = await message.reply_text(
        "⏳ در حال تبدیل صدا به متن، لطفاً صبر کن..."
    )

    try:
        audio_file = message.voice or message.audio

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = str(Path(temp_dir) / "input_audio")
            wav_path = str(Path(temp_dir) / "converted.wav")

            telegram_file = await context.bot.get_file(
                audio_file.file_id
            )

            await telegram_file.download_to_drive(input_path)

            # تبدیل فایل تلگرام به WAV قابل پردازش
            audio = AudioSegment.from_file(input_path)
            audio = audio.set_channels(1).set_frame_rate(16000)
            audio.export(wav_path, format="wav")

            recognizer = sr.Recognizer()

            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)

            # سرویس آنلاین رایگان گوگل؛ بدون API Key
            result = await asyncio.to_thread(
                recognizer.recognize_google,
                audio_data,
                language="fa-IR"
            )

        await status.delete()

        await message.reply_text(
            "📝 متن تشخیص‌داده‌شده:\n\n" + result,
            reply_markup=main_keyboard()
        )

    except sr.UnknownValueError:
        await status.edit_text(
            "❌ صدای واضحی تشخیص داده نشد. لطفاً یک ویس واضح‌تر بفرست."
        )

    except sr.RequestError:
        await status.edit_text(
            "❌ سرویس تشخیص گفتار در دسترس نیست. کمی بعد دوباره امتحان کن."
        )

    except Exception as e:
        import traceback
        import traceback
        print("VOICE TO TEXT ERROR:", repr(e))
        traceback.print_exc()
        traceback.print_exc()
        await status.edit_text(
            "❌ تبدیل صدا انجام نشد. لطفاً فایل صوتی دیگری بفرست."
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    print(
        "BOT ERROR:",
        repr(context.error)
    )



