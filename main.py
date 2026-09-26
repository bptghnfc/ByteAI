from pathlib import Path
import os

from dotenv import load_dotenv

# =========================================================
# ENV
# =========================================================

load_dotenv(Path(__file__).resolve().parent / ".env")

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import image_service
import ai_service
import voice_service


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8394607974"))


# =========================================================
# API MANAGEMENT
# =========================================================

def mask_api(value):
    value = (value or "").strip()

    if not value:
        return "تنظیم نشده ❌"

    if len(value) <= 8:
        return "••••••••"

    return "••••••••" + value[-4:]


def update_env_value(key, value):
    env_path = Path(__file__).resolve().parent / ".env"

    if env_path.exists():
        lines = env_path.read_text().splitlines()
    else:
        lines = []

    found = False
    new_lines = []

    for line in lines:
        if line.startswith(key + "="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")

    os.environ[key] = value


def reload_runtime_api():
    # Reload AI settings
    ai_service.DAHL_API_KEY = os.getenv("DAHL_API_KEY", "")
    ai_service.DAHL_MODEL = os.getenv(
        "DAHL_MODEL",
        "MiniMaxAI/MiniMax-M2.7"
    )

    from openai import OpenAI

    ai_service.client = OpenAI(
        api_key=ai_service.DAHL_API_KEY,
        base_url="https://inference.dahl.global/v1",
    )

    # Reload Cloudflare settings
    image_service.DEFAULT_CF_ACCOUNT_ID = os.getenv(
        "CF_ACCOUNT_ID",
        ""
    )

    image_service.DEFAULT_CF_API_TOKEN = os.getenv(
        "CF_API_TOKEN",
        ""
    )




async def cancel_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.pop("api_edit", None)

    await update.message.reply_text(
        "❌ تغییر API لغو شد."
    )


async def api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return

    context.user_data.pop("api_edit", None)

    await show_api_panel(update)


async def show_api_panel(update: Update):
    ai_key = os.getenv("DAHL_API_KEY", "")
    ai_model = os.getenv(
        "DAHL_MODEL",
        "MiniMaxAI/MiniMax-M2.7"
    )

    cf_account = os.getenv("CF_ACCOUNT_ID", "")
    cf_token = os.getenv("CF_API_TOKEN", "")

    text = (
        "🔐 مدیریت API های ByteAI\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 Ramin AI\n"
        f"🔑 API Key: {mask_api(ai_key)}\n"
        f"🧠 Model: {ai_model}\n\n"
        "🎨 ساخت تصویر\n"
        f"🆔 Account ID: {mask_api(cf_account)}\n"
        f"🔑 API Token: {mask_api(cf_token)}\n\n"
        "🎙️ تبدیل ویس\n"
        "ℹ️ بدون API جداگانه\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 برای تغییر، بخش موردنظر را انتخاب کن."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🤖 تنظیمات Ramin AI",
                callback_data="api_ai"
            )
        ],
        [
            InlineKeyboardButton(
                "🎨 تنظیمات ساخت تصویر",
                callback_data="api_image"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 بروزرسانی",
                callback_data="api_refresh"
            )
        ],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )


async def api_callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    await query.answer()

    data = query.data

    if data == "api_refresh":
        await show_api_panel(update)
        return

    if data == "api_ai":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔑 تغییر API Key",
                    callback_data="api_set_ai_key"
                )
            ],
            [
                InlineKeyboardButton(
                    "🧠 تغییر Model",
                    callback_data="api_set_ai_model"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 برگشت",
                    callback_data="api_refresh"
                )
            ],
        ])

        await query.edit_message_text(
            "🤖 تنظیمات Ramin AI\n\n"
            "👇 موردی که می‌خوای تغییر بدی رو انتخاب کن:",
            reply_markup=keyboard
        )
        return

    if data == "api_image":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🆔 تغییر Account ID",
                    callback_data="api_set_cf_account"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔑 تغییر API Token",
                    callback_data="api_set_cf_token"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 برگشت",
                    callback_data="api_refresh"
                )
            ],
        ])

        await query.edit_message_text(
            "🎨 تنظیمات ساخت تصویر\n\n"
            "👇 موردی که می‌خوای تغییر بدی رو انتخاب کن:",
            reply_markup=keyboard
        )
        return

    fields = {
        "api_set_ai_key": (
            "DAHL_API_KEY",
            "🔑 API Key جدید Ramin AI رو ارسال کن:"
        ),
        "api_set_ai_model": (
            "DAHL_MODEL",
            "🧠 نام Model جدید رو ارسال کن:"
        ),
        "api_set_cf_account": (
            "CF_ACCOUNT_ID",
            "🆔 Cloudflare Account ID جدید رو ارسال کن:"
        ),
        "api_set_cf_token": (
            "CF_API_TOKEN",
            "🔑 Cloudflare API Token جدید رو ارسال کن:"
        ),
    }

    if data in fields:
        key, message = fields[data]

        context.user_data["api_edit"] = key

        await query.edit_message_text(
            message + "\n\n"
            "❌ برای لغو، /cancel رو بفرست."
        )
        return


async def handle_api_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != ADMIN_ID:
        context.user_data.pop("api_edit", None)
        return False

    key = context.user_data.get("api_edit")

    if not key:
        return False

    value = update.message.text.strip()

    if not value:
        await update.message.reply_text("❌ مقدار نمی‌تونه خالی باشه.")
        return True

    update_env_value(key, value)

    # Reload .env values
    load_dotenv(
        Path(__file__).resolve().parent / ".env",
        override=True
    )

    reload_runtime_api()

    context.user_data.pop("api_edit", None)

    await update.message.reply_text(
        "✅ با موفقیت تغییر کرد!\n\n"
        f"🔧 {key}\n\n"
        "⚡ مقدار جدید ذخیره شد و سرویس هم بروزرسانی شد."
    )

    await show_api_panel(update)

    return True


# =========================================================
# MAIN KEYBOARD
# =========================================================

def main_keyboard(user_id=None):
    rows = [
        ["💬 چت با هوش مصنوعی", "🖼️ ساخت تصویر"],
        ["🎙️ تبدیل متن به ویس", "🎤 تبدیل ویس به متن"],
        ["ℹ️ اطلاعات"],
    ]

    if user_id == ADMIN_ID:
        rows.append(["👑 پنل مدیریت"])

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True
    )

    if user_id == ADMIN_ID:
        rows.append(["👑 پنل مدیریت"])

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True
    )

# =========================================================
# FORCE JOIN
# =========================================================

FORCE_CHANNEL = "@ByteTunnel"


async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(FORCE_CHANNEL, user_id)

        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }

    except Exception as e:
        print(f"Membership check error: {e}")
        return False


async def send_join(update):
    keyboard = ReplyKeyboardMarkup(
        [
            ["📢 عضویت در کانال"],
            ["✅ بررسی عضویت"],
        ],
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🔒 عضویت اجباری\n\n"
        "برای استفاده از ByteAI ابتدا باید عضو کانال ما بشی.\n\n"
        "📢 کانال: @ByteTunnel\n\n"
        "بعد از عضویت روی «✅ بررسی عضویت» بزن.",
        reply_markup=keyboard
    )


# =========================================================
# START
# =========================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    context.user_data.clear()

    # بررسی عضویت اجباری هنگام /start
    if not await is_member(context.bot, user.id):
        await send_join(update)
        return

    await update.message.reply_text(
        "👋 سلام رفیق، خوش اومدی به ByteAI 🤖✨\n\n"
        "✅ عضویتت با موفقیت تأیید شد!\n\n"
        "❤️ ممنون که از بات ما استفاده می‌کنی.\n"
        "🎁 همه امکانات ByteAI کاملاً رایگانه و در اختیارت قرار داره! 🚀",
        reply_markup=main_keyboard(user.id)
    )


# =========================================================
# MAIN MENU
# =========================================================

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    context.user_data.clear()

    await update.message.reply_text(
        "🏠 به منوی اصلی برگشتی.\n\n"
        "👇 یک سرویس انتخاب کن:",
        reply_markup=main_keyboard(user.id)
    )


# =========================================================
# IMAGE MODULE
# =========================================================

async def open_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    context.user_data["service"] = "image"

    await image_service.ask_image(update)


# =========================================================
# AI MODULE
# =========================================================

async def open_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    context.user_data["service"] = "ai"
    context.user_data["mode"] = "chat"

    # Let the original AI module show its own menu.
    await ai_service.start(update, context)


# =========================================================
# VOICE MODULE
# =========================================================

async def open_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    context.user_data["service"] = "voice"

    await voice_service.voice_menu(update, context)


# =========================================================
# VOICE TO TEXT
# =========================================================

async def open_voice_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    context.user_data["service"] = "voice_to_text"

    await update.message.reply_text(
        "🎤 تبدیل ویس به متن فعال شد.\n\n"
        "🎧 ویس یا فایل صوتی خودت رو بفرست.\n\n"
        "برای برگشت به منوی اصلی:\n"
        "🏠 منوی اصلی",
        reply_markup=ReplyKeyboardMarkup(
            [["🏠 منوی اصلی"]],
            resize_keyboard=True
        )
    )


# =========================================================
# SETTINGS
# =========================================================

async def information(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ درباره ByteAI\n\n"
        "🤖 به ByteAI خوش اومدی!\n\n"
        "این بات با هدف ارائه ابزارهای هوش مصنوعی به‌صورت رایگان ساخته شده "
        "تا همه بتونن راحت‌تر از امکانات هوش مصنوعی استفاده کنن.\n\n"
        "✨ امکانات بات:\n"
        "💬 چت با هوش مصنوعی\n"
        "🖼️ ساخت تصویر با هوش مصنوعی\n"
        "🎙️ تبدیل متن به ویس\n"
        "🎤 تبدیل ویس به متن\n\n"
        "👨‍💻 سازنده: Ramin\n\n"
        "📢 کانال ما: @ByteTunnel\n\n"
        "❤️ ممنون که از ByteAI استفاده می‌کنی. "
        "امیدواریم کنار هم روزهای خوبی بسازیم!",
        reply_markup=main_keyboard(update.effective_user.id)
    )


# =========================================================
# ADMIN
# =========================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return

    context.user_data.clear()
    context.user_data["service"] = "ai"

    await ai_service.admin(update, context)


# =========================================================
# TEXT ROUTER
# =========================================================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # API management input
    if await handle_api_text(update, context):
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user

    service = context.user_data.get("service")

    # =====================================================
    # FORCE JOIN
    # =====================================================

    if text == "📢 عضویت در کانال":
        await update.message.reply_text(
            "📢 برای عضویت در کانال روی لینک زیر بزن:\n\n"
            "https://t.me/ByteTunnel"
        )
        return

    if text == "✅ بررسی عضویت":
        if await is_member(context.bot, user.id):
            context.user_data.clear()

            await update.message.reply_text(
                "✅ عضویت شما تأیید شد!\n\n"
                "🤖 حالا می‌تونی از ByteAI استفاده کنی.",
                reply_markup=main_keyboard(user.id)
            )
        else:
            await send_join(update)

        return

    # =====================================================
    # GLOBAL MAIN MENU
    # =====================================================

    if text in ("🏠 منوی اصلی", "🔙 منوی اصلی"):
        await main_menu(update, context)
        return

    # =====================================================
    # GLOBAL MODULE BUTTONS
    # =====================================================

    if text == "💬 چت با هوش مصنوعی":
        await open_ai(update, context)
        return

    if text == "🖼️ ساخت تصویر":
        await open_image(update, context)
        return

    if text == "🎙️ تبدیل متن به ویس":
        await open_voice(update, context)
        return

    if text == "🎤 تبدیل ویس به متن":
        await open_voice_to_text(update, context)
        return

    if text == "ℹ️ اطلاعات":
        await information(update, context)
        return

    if text == "👑 پنل مدیریت":
        await admin_panel(update, context)
        return

    # =====================================================
    # IMAGE MODULE
    # =====================================================

    if service == "image":
        await image_service.message_router(update, context)
        return

    # =====================================================
    # AI MODULE
    # =====================================================

    if service == "ai":
        await ai_service.handle_text(update, context)
        return

    # =====================================================
    # VOICE MODULE
    # =====================================================

    if service == "voice":
        await voice_service.button_router(update, context)
        return

    # =====================================================
    # DEFAULT
    # =====================================================

    await update.message.reply_text(
        "👇 از منوی پایین یک سرویس انتخاب کن.",
        reply_markup=main_keyboard(user.id)
    )


# =========================================================
# AUDIO ROUTER
# =========================================================

async def audio_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service = context.user_data.get("service")

    if service == "voice_to_text":
        await voice_service.voice_to_text(update, context)
        return

    await update.message.reply_text(
        "🎤 ابتدا «🎤 تبدیل ویس به متن» را انتخاب کن.",
        reply_markup=main_keyboard(update.effective_user.id)
    )


# =========================================================
# IMAGE CALLBACK ROUTER
# =========================================================

async def image_callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    # Image callbacks belong to the image module.
    context.user_data["service"] = "image"

    await image_service.callbacks(update, context)


# =========================================================
# ERROR
# =========================================================

async def error_handler(update, context):
    print("BOT ERROR:", repr(context.error))


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

    # Initialize existing databases.
    try:
        image_service.init_db()
    except Exception as e:
        print("IMAGE DB:", repr(e))

    try:
        ai_service.init_db()
    except Exception as e:
        print("AI DB:", repr(e))

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler("start", start)
    )

    # /api
    app.add_handler(
        CommandHandler("api", api_command)
    )

    # /cancel API editing
    app.add_handler(
        CommandHandler("cancel", cancel_api)
    )

    # API callbacks
    app.add_handler(
        CallbackQueryHandler(
            api_callback_router,
            pattern=r"^api_"
        )
    )

    # Image callback buttons
    app.add_handler(
        CallbackQueryHandler(image_callback_router)
    )

    # Text messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router
        )
    )

    # Voice / audio
    app.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO,
            audio_router
        )
    )

    app.add_error_handler(error_handler)

    print("🤖 ByteAI is running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
