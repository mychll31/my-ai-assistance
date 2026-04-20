import logging
import os

import requests as http
from flask import Flask, request

from ai_parser import parse_event
from calendar_service import CalendarService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
calendar = CalendarService()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("AUTHORIZED_USER_ID") or "0")


def send(chat_id: int, text: str):
    http.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )


def handle(chat_id: int, text: str):
    if text == "/start":
        send(chat_id,
             "Hi! I'm your AI calendar bot.\n\n"
             "Send me any event like:\n"
             "• Meeting with Sarah tomorrow 2pm\n"
             "• Dentist Friday 10am for 30 min\n"
             "• Team lunch next Monday noon\n\n"
             "First, connect Google Calendar with /auth")

    elif text == "/auth":
        send(chat_id, f"Authorize Google Calendar:\n\n{calendar.get_auth_url()}")

    elif text == "/status":
        if calendar.is_authenticated():
            send(chat_id, "Google Calendar is connected.")
        else:
            send(chat_id, "Not connected. Use /auth")

    elif not text.startswith("/"):
        if not calendar.is_authenticated():
            send(chat_id, "Connect Google Calendar first: /auth")
            return
        send(chat_id, "Adding event...")
        try:
            tz = os.environ.get("TIMEZONE", "Asia/Manila")
            event_data = parse_event(text, tz)
            if not event_data:
                send(chat_id, "Doesn't look like a calendar event.\nTry: Meeting with John tomorrow 3pm")
            else:
                event = calendar.create_event(event_data)
                start = event_data["start_datetime"].replace("T", " ")[:16]
                send(chat_id, f"Added!\n\n{event_data['title']}\n{start}\n{event.get('htmlLink', '')}")
        except Exception:
            logger.exception("Failed to create event")
            send(chat_id, "Something went wrong. Please try again.")


@app.route("/api/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or data.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    user_id = message.get("from", {}).get("id")

    if chat_id and text and (not OWNER_ID or user_id == OWNER_ID):
        handle(chat_id, text)

    return "OK"


@app.route("/api/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "<h2>Missing code.</h2>", 400

    refresh_token = calendar.handle_callback(code)
    if refresh_token:
        if OWNER_ID and BOT_TOKEN:
            http.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": OWNER_ID,
                    "text": (
                        "Google Calendar connected!\n\n"
                        "Add this in Vercel dashboard → Settings → Environment Variables:\n\n"
                        f"GOOGLE_REFRESH_TOKEN={refresh_token}\n\n"
                        "Then redeploy. You only need to do this once."
                    ),
                },
                timeout=10,
            )
        return "<h2>Connected!</h2><p>Check Telegram for your token.</p>"
    return "<h2>Failed.</h2><p>Try /auth again in Telegram.</p>", 400


@app.route("/health")
def health():
    return "OK"
