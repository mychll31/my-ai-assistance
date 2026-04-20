import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as http
from ai_parser import parse_intent
from calendar_service import CalendarService
from gmail_service import GmailService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

calendar = CalendarService()
gmail = GmailService(calendar)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("AUTHORIZED_USER_ID") or "0")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Best-effort inbox cache per user (Fluid Compute reuses instances within a region)
_inbox_cache: dict[int, list[dict]] = {}


def send(chat_id: int, text: str):
    http.post(f"{TG_API}/sendMessage", json={
        "chat_id": chat_id, "text": text, "disable_web_page_preview": True,
    }, timeout=10)


def sender_name(from_header: str) -> str:
    if "<" in from_header:
        return from_header.split("<")[0].strip().strip('"')
    return from_header


def resolve_index(intent: dict, inbox: list) -> int | None:
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


def transcribe_voice(file_id: str) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
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


def do_inbox(chat_id: int, user_id: int):
    if not calendar.is_authenticated():
        send(chat_id, "Connect Google first: /auth")
        return
    try:
        emails = gmail.list_unread()
    except Exception:
        logger.exception("list_unread failed")
        send(chat_id, "Failed to fetch emails. Try /auth to reconnect.")
        return
    _inbox_cache[user_id] = emails
    if not emails:
        send(chat_id, "No unread emails.")
        return
    lines = ["Unread emails:\n"]
    for i, e in enumerate(emails, 1):
        lines.append(f"{i}. {sender_name(e['from'])}: {e['subject']}\n   {e['snippet'][:80]}")
    send(chat_id, "\n".join(lines))


def process_text(chat_id: int, user_id: int, text: str):
    if not calendar.is_authenticated():
        send(chat_id, "Connect Google first: /auth")
        return

    tz = os.environ.get("TIMEZONE", "UTC")
    inbox = _inbox_cache.get(user_id)
    intent = parse_intent(text, tz, inbox)

    if intent is None:
        send(chat_id,
             "Doesn't look like a calendar event or email command.\n\n"
             "Try:\n• Meeting with John tomorrow at 3pm\n• Show my inbox\n• Reply to Sarah saying I'll be there")
        return

    t = intent["type"]

    if t == "calendar":
        send(chat_id, "Adding event...")
        event = calendar.create_event(intent)
        start = intent["start_datetime"].replace("T", " ")[:16]
        send(chat_id, f"Added!\n\n{intent['title']}\n{start}\n{event.get('htmlLink', '')}")

    elif t == "email_list":
        do_inbox(chat_id, user_id)

    elif t == "email_read":
        if not inbox:
            send(chat_id, "Use /inbox first to load your emails.")
            return
        idx = resolve_index(intent, inbox)
        if idx is None:
            send(chat_id, "Couldn't find that email. Try /inbox to refresh.")
            return
        e = inbox[idx]
        body = gmail.get_body(e["id"])
        send(chat_id, f"From: {e['from']}\nSubject: {e['subject']}\n\n{body[:3000]}")

    elif t == "email_reply":
        if not inbox:
            inbox = gmail.list_unread()
            _inbox_cache[user_id] = inbox
        idx = resolve_index(intent, inbox)
        if idx is None:
            send(chat_id, "Couldn't find that email. Try /inbox to refresh.")
            return
        e = inbox[idx]
        gmail.reply(e["id"], e["thread_id"], e["from"], e["subject"], intent.get("body", ""))
        send(chat_id, f"Replied to {sender_name(e['from'])}")

    elif t == "email_send":
        gmail.send(intent["to"], intent["subject"], intent["body"])
        send(chat_id, f"Sent to {intent['to']}")


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
                self._handle_text(chat_id, user_id, text)
            elif voice:
                self._handle_voice(chat_id, user_id, voice["file_id"])
            elif message.get("audio") or message.get("document"):
                send(chat_id, "Please send a voice message (hold mic button in Telegram).")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def _handle_text(self, chat_id: int, user_id: int, text: str):
        if text == "/start":
            send(chat_id,
                 "Hi! I'm your AI assistant.\n\n"
                 "Calendar — describe an event:\n"
                 "• Meeting with Sarah tomorrow 2pm\n\n"
                 "Email:\n"
                 "• /inbox — show unread emails\n"
                 "• /read 2 — read email #2\n"
                 "• /reply 2 I'll be there! — reply\n"
                 "• Or describe it naturally / by voice\n\n"
                 "Commands: /auth /status /inbox")
        elif text == "/auth":
            send(chat_id, f"Authorize Google Calendar & Gmail:\n\n{calendar.get_auth_url()}")
        elif text == "/status":
            if calendar.is_authenticated():
                send(chat_id, "Google Calendar & Gmail are connected.")
            else:
                send(chat_id, "Not connected. Use /auth")
        elif text == "/inbox":
            do_inbox(chat_id, user_id)
        elif text.startswith("/read"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].isdigit():
                send(chat_id, "Usage: /read <number>  e.g. /read 2")
                return
            inbox = _inbox_cache.get(user_id)
            if not inbox:
                send(chat_id, "Use /inbox first to load your emails.")
                return
            idx = int(parts[1]) - 1
            if not (0 <= idx < len(inbox)):
                send(chat_id, f"No email #{idx + 1}. Use /inbox to refresh.")
                return
            e = inbox[idx]
            body = gmail.get_body(e["id"])
            send(chat_id, f"From: {e['from']}\nSubject: {e['subject']}\n\n{body[:3000]}")
        elif text.startswith("/reply"):
            parts = text.split(maxsplit=2)
            if len(parts) < 3 or not parts[1].isdigit():
                send(chat_id, "Usage: /reply <number> <message>  e.g. /reply 2 Sure!")
                return
            inbox = _inbox_cache.get(user_id)
            if not inbox:
                send(chat_id, "Use /inbox first to load your emails.")
                return
            idx = int(parts[1]) - 1
            if not (0 <= idx < len(inbox)):
                send(chat_id, f"No email #{idx + 1}. Use /inbox to refresh.")
                return
            e = inbox[idx]
            gmail.reply(e["id"], e["thread_id"], e["from"], e["subject"], parts[2])
            send(chat_id, f"Replied to {sender_name(e['from'])}")
        elif not text.startswith("/"):
            process_text(chat_id, user_id, text)

    def _handle_voice(self, chat_id: int, user_id: int, file_id: str):
        if not calendar.is_authenticated():
            send(chat_id, "Connect Google first: /auth")
            return
        send(chat_id, "Transcribing...")
        try:
            transcription = transcribe_voice(file_id)
        except Exception:
            logger.exception("transcribe_voice failed")
            send(chat_id, "Transcription failed. Please try again.")
            return
        if not transcription:
            send(chat_id, "Couldn't transcribe. Check OPENAI_API_KEY or GROQ_API_KEY is set.")
            return
        send(chat_id, f'Heard: "{transcription}"\n\nProcessing...')
        process_text(chat_id, user_id, transcription)

    def log_message(self, *args):
        pass
