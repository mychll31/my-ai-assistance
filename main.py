import asyncio
import logging
import os
import signal
from dotenv import load_dotenv

load_dotenv()

from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from ai_parser import parse_intent
from calendar_service import CalendarService
from gmail_service import GmailService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

calendar = CalendarService()
gmail = GmailService(calendar)
_owner_id = int(os.environ.get("AUTHORIZED_USER_ID") or "0")


def _ok(update: Update) -> bool:
    return _owner_id == 0 or update.effective_user.id == _owner_id


def _sender_name(from_header: str) -> str:
    if "<" in from_header:
        return from_header.split("<")[0].strip().strip('"')
    return from_header


def _resolve_index(intent: dict, inbox: list | None) -> int | None:
    """Returns 0-based inbox index matching intent's index or sender_name, or None."""
    if not inbox:
        return None
    idx = intent.get("index")
    if idx is not None:
        i = int(idx) - 1
        return i if 0 <= i < len(inbox) else None
    name = (intent.get("sender_name") or "").lower()
    if name:
        for i, e in enumerate(inbox):
            if name in e["from"].lower() or name in e["subject"].lower():
                return i
    return None


async def _process_text(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE, status_msg=None):
    async def reply(msg):
        if status_msg:
            await status_msg.edit_text(msg, disable_web_page_preview=True)
        else:
            await update.message.reply_text(msg, disable_web_page_preview=True)

    tz = os.environ.get("TIMEZONE", "UTC")
    inbox = context.user_data.get("inbox")
    intent = await asyncio.to_thread(parse_intent, text, tz, inbox)

    if intent is None:
        await reply(
            "Doesn't look like a calendar event or email command.\n\n"
            "Try:\n"
            "• Meeting with John tomorrow at 3pm\n"
            "• Show my inbox\n"
            "• Reply to Sarah saying I'll be there"
        )
        return

    t = intent["type"]

    if t == "calendar":
        event = await asyncio.to_thread(calendar.create_event, intent)
        start = intent["start_datetime"].replace("T", " ")[:16]
        await reply(
            f"Added!\n\n{intent['title']}\n{start}\n{event.get('htmlLink', '')}"
        )

    elif t == "email_list":
        emails = await asyncio.to_thread(gmail.list_unread)
        if not emails:
            await reply("No unread emails.")
            return
        context.user_data["inbox"] = emails
        lines = ["Unread emails:\n"]
        for i, e in enumerate(emails, 1):
            lines.append(f"{i}. {_sender_name(e['from'])}: {e['subject']}\n   {e['snippet'][:80]}")
        await reply("\n".join(lines))

    elif t == "email_read":
        idx = _resolve_index(intent, inbox)
        if idx is None:
            await reply("Use /inbox first to list your emails, then ask to read one by number.")
            return
        e = inbox[idx]
        body = await asyncio.to_thread(gmail.get_body, e["id"])
        await reply(f"From: {e['from']}\nSubject: {e['subject']}\n\n{body[:3000]}")

    elif t == "email_reply":
        idx = _resolve_index(intent, inbox)
        if idx is None:
            await reply("Use /inbox first to list your emails, then ask to reply to one by number.")
            return
        e = inbox[idx]
        body = intent.get("body", "")
        await asyncio.to_thread(gmail.reply, e["id"], e["thread_id"], e["from"], e["subject"], body)
        await reply(f"Replied to {_sender_name(e['from'])}")

    elif t == "email_send":
        await asyncio.to_thread(gmail.send, intent["to"], intent["subject"], intent["body"])
        await reply(f"Sent to {intent['to']}")


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text(
        "Hi! I'm your AI assistant. I can:\n\n"
        "Calendar: just describe an event\n"
        "• Meeting with Sarah tomorrow at 2pm\n"
        "• Dentist Friday 10am for 30 minutes\n\n"
        "Email:\n"
        "• /inbox — show unread emails\n"
        "• /read 2 — read email #2\n"
        "• /reply 2 Sure, I'll be there! — reply to email #2\n"
        "• Or just describe it in natural language\n\n"
        "Voice messages work too! Connect Google first: /auth"
    )


async def cmd_auth(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text(
        f"Authorize Google Calendar & Gmail access:\n\n{calendar.get_auth_url()}"
    )


async def cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if calendar.is_authenticated():
        await update.message.reply_text("Google Calendar & Gmail are connected.")
    else:
        await update.message.reply_text("Not connected. Use /auth to connect.")


async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not calendar.is_authenticated():
        await update.message.reply_text("Connect Google first: /auth")
        return
    status = await update.message.reply_text("Fetching inbox...")
    try:
        emails = await asyncio.to_thread(gmail.list_unread)
        if not emails:
            await status.edit_text("No unread emails.")
            return
        context.user_data["inbox"] = emails
        lines = ["Unread emails:\n"]
        for i, e in enumerate(emails, 1):
            lines.append(f"{i}. {_sender_name(e['from'])}: {e['subject']}\n   {e['snippet'][:80]}")
        await status.edit_text("\n".join(lines))
    except Exception:
        logger.exception("cmd_inbox failed")
        await status.edit_text("Something went wrong. Please try again.")


async def cmd_read(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not calendar.is_authenticated():
        await update.message.reply_text("Connect Google first: /auth")
        return
    inbox = context.user_data.get("inbox")
    if not inbox:
        await update.message.reply_text("Use /inbox first to load your emails.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /read <number>  (e.g. /read 2)")
        return
    idx = int(args[0]) - 1
    if not (0 <= idx < len(inbox)):
        await update.message.reply_text(f"No email #{idx + 1}. Use /inbox to refresh.")
        return
    status = await update.message.reply_text("Reading...")
    try:
        e = inbox[idx]
        body = await asyncio.to_thread(gmail.get_body, e["id"])
        await status.edit_text(f"From: {e['from']}\nSubject: {e['subject']}\n\n{body[:3000]}")
    except Exception:
        logger.exception("cmd_read failed")
        await status.edit_text("Something went wrong. Please try again.")


async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not calendar.is_authenticated():
        await update.message.reply_text("Connect Google first: /auth")
        return
    inbox = context.user_data.get("inbox")
    if not inbox:
        await update.message.reply_text("Use /inbox first to load your emails.")
        return
    args = context.args
    if len(args) < 2 or not args[0].isdigit():
        await update.message.reply_text("Usage: /reply <number> <message>  (e.g. /reply 2 Sure, I'll be there!)")
        return
    idx = int(args[0]) - 1
    if not (0 <= idx < len(inbox)):
        await update.message.reply_text(f"No email #{idx + 1}. Use /inbox to refresh.")
        return
    reply_body = " ".join(args[1:])
    status = await update.message.reply_text("Sending reply...")
    try:
        e = inbox[idx]
        await asyncio.to_thread(gmail.reply, e["id"], e["thread_id"], e["from"], e["subject"], reply_body)
        await status.edit_text(f"Replied to {_sender_name(e['from'])}")
    except Exception:
        logger.exception("cmd_reply failed")
        await status.edit_text("Something went wrong. Please try again.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not calendar.is_authenticated():
        await update.message.reply_text("Connect Google first: /auth")
        return

    status = await update.message.reply_text("Transcribing...")
    try:
        file = await update.message.voice.get_file()
        voice_bytes = bytes(await file.download_as_bytearray())

        import openai
        oai = openai.AsyncOpenAI()
        transcript = await oai.audio.transcriptions.create(
            model="whisper-1",
            file=("voice.ogg", voice_bytes, "audio/ogg"),
        )
        text = transcript.text.strip()
        if not text:
            await status.edit_text("Couldn't transcribe the voice message.")
            return

        await status.edit_text(f'Heard: "{text}"\n\nProcessing...')
        await _process_text(text, update, context, status)
    except Exception:
        logger.exception("handle_voice failed")
        await status.edit_text("Something went wrong. Please try again.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not calendar.is_authenticated():
        await update.message.reply_text("Connect Google first: /auth")
        return

    status = await update.message.reply_text("Processing...")
    try:
        await _process_text(update.message.text, update, context, status)
    except Exception:
        logger.exception("handle_message failed")
        await status.edit_text("Something went wrong. Please try again.")


async def oauth_callback(request: web.Request) -> web.Response:
    code = request.query.get("code")
    if not code:
        return web.Response(text="Missing code", status=400)

    refresh_token = calendar.handle_callback(code)
    if refresh_token:
        if _owner_id:
            try:
                bot_app: Application = request.app["bot"]
                await bot_app.bot.send_message(
                    _owner_id,
                    f"Google Calendar & Gmail connected!\n\n"
                    f"To survive restarts, add this env var:\n\n"
                    f"GOOGLE_REFRESH_TOKEN={refresh_token}\n\n"
                    f"You only need to do this once.",
                )
            except Exception:
                logger.exception("Could not send refresh token via Telegram")
        return web.Response(
            content_type="text/html",
            text="<h2>Connected!</h2><p>Check Telegram for next steps!</p>",
        )
    return web.Response(
        content_type="text/html",
        text="<h2>Failed.</h2><p>Try /auth again in Telegram.</p>",
        status=400,
    )


async def health(_: web.Request) -> web.Response:
    return web.Response(text="OK")


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    bot = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    bot.add_handler(CommandHandler("start", cmd_start))
    bot.add_handler(CommandHandler("auth", cmd_auth))
    bot.add_handler(CommandHandler("status", cmd_status))
    bot.add_handler(CommandHandler("inbox", cmd_inbox))
    bot.add_handler(CommandHandler("read", cmd_read))
    bot.add_handler(CommandHandler("reply", cmd_reply))
    bot.add_handler(MessageHandler(filters.VOICE, handle_voice))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    web_app = web.Application()
    web_app["bot"] = bot
    web_app.router.add_get("/oauth/callback", oauth_callback)
    web_app.router.add_get("/health", health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"Web server on :{port}")

    async with bot:
        await bot.initialize()
        await bot.start()
        await bot.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot polling started")
        await stop.wait()
        await bot.updater.stop()
        await bot.stop()

    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
