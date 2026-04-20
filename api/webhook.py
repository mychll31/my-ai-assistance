import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as http
from ai_parser import parse_event
from calendar_service import CalendarService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

calendar = CalendarService()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("AUTHORIZED_USER_ID") or "0")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send(chat_id: int, text: str):
    http.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)


def transcribe_voice(file_id: str) -> str | None:
    """Download voice OGG from Telegram and transcribe via Whisper."""
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    # Use Groq if GROQ_API_KEY is set, otherwise OpenAI
    using_groq = bool(os.environ.get("GROQ_API_KEY"))
    base_url = "https://api.groq.com/openai/v1" if using_groq else "https://api.openai.com/v1"
    model = "whisper-large-v3-turbo" if using_groq else "whisper-1"

    file_info = http.get(f"{TG_API}/getFile?file_id={file_id}", timeout=10).json()
    file_path = file_info.get("result", {}).get("file_path")
    if not file_path:
        return None

    audio = http.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}", timeout=30)

    resp = http.post(
        f"{base_url}/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": ("voice.ogg", audio.content, "audio/ogg")},
        data={"model": model},
        timeout=30,
    )
    return resp.json().get("text")


def process_event(chat_id: int, text: str):
    if not calendar.is_authenticated():
        send(chat_id, "Connect Google Calendar first: /auth")
        return
    send(chat_id, "Adding event...")
    try:
        tz = os.environ.get("TIMEZONE", "UTC")
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


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        message = body.get("message") or body.get("edited_message") or {}
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        text = (message.get("text") or "").strip()
        voice = message.get("voice")

        if chat_id and (not OWNER_ID or user_id == OWNER_ID):
            if text:
                self._handle_text(chat_id, text)
            elif voice:
                self._handle_voice(chat_id, voice["file_id"])
            elif message.get("audio") or message.get("document"):
                send(chat_id, "Please send a voice message (hold mic button in Telegram).")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def _handle_text(self, chat_id: int, text: str):
        if text == "/start":
            send(chat_id,
                 "Hi! I'm your AI calendar bot.\n\n"
                 "Send text or a voice message like:\n"
                 "• Meeting with Sarah tomorrow 2pm\n"
                 "• Dentist Friday 10am for 30 min\n\n"
                 "Commands: /auth /status")
        elif text == "/auth":
            send(chat_id, f"Authorize Google Calendar:\n\n{calendar.get_auth_url()}")
        elif text == "/status":
            if calendar.is_authenticated():
                send(chat_id, "Google Calendar is connected.")
            else:
                send(chat_id, "Not connected. Use /auth")
        elif not text.startswith("/"):
            process_event(chat_id, text)

    def _handle_voice(self, chat_id: int, file_id: str):
        if not calendar.is_authenticated():
            send(chat_id, "Connect Google Calendar first: /auth")
            return
        send(chat_id, "Transcribing voice message...")
        try:
            transcription = transcribe_voice(file_id)
        except Exception as e:
            send(chat_id, f"Transcription error: {e}")
            logger.exception("transcribe_voice failed")
            return
        if not transcription:
            send(chat_id, "Couldn't transcribe. Check GROQ_API_KEY or OPENAI_API_KEY is set in Vercel.")
            return
        send(chat_id, f"Heard: {transcription}\n\nAdding to calendar...")
        process_event(chat_id, transcription)

    def log_message(self, *args):
        pass
