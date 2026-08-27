import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests as http
from flask import Flask, request

from ai_parser import parse_intent
from calendar_service import CalendarService, format_conflicts
from contacts_service import ContactsService
from gmail_service import GmailService
from zoom_service import ZoomNotConfigured, ZoomService, duration_minutes
from googleapiclient.errors import HttpError
from tasks_service import TasksService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
calendar = CalendarService()
gmail = GmailService(calendar)
tasks = TasksService(calendar)
contacts = ContactsService(calendar)
zoom = ZoomService()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("AUTHORIZED_USER_ID") or "0")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

_inbox_cache: dict[int, list[dict]] = {}
_tasks_cache: dict[int, list[dict]] = {}


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
    except Exception as e:
        logger.exception("list_unread failed")
        send(chat_id, f"Failed to fetch emails: {e}\n\nTry /auth to reconnect.")
        return
    _inbox_cache[user_id] = emails
    if not emails:
        send(chat_id, "No unread emails.")
        return
    lines = ["Unread emails:\n"]
    for i, e in enumerate(emails, 1):
        lines.append(f"{i}. {sender_name(e['from'])}: {e['subject']}\n   {e['snippet'][:80]}")
    send(chat_id, "\n".join(lines))


def _needs_reauth(chat_id: int, e: Exception) -> bool:
    """Tasks fails with 403 two different ways, and the fixes are unrelated."""
    if not (isinstance(e, HttpError) and e.resp.status == 403):
        return False
    body = (getattr(e, "content", b"") or b"").decode("utf-8", "replace")
    if "accessNotConfigured" in body or "has not been used in project" in body:
        send(chat_id, "The Google Tasks API isn't enabled on your Google Cloud project.\n\n"
                      "Enable it at console.cloud.google.com \u2192 APIs & Services \u2192 Library "
                      "\u2192 Google Tasks API, then try again in a minute.")
    else:
        send(chat_id, "Tasks isn't authorized on this token yet.\n\n"
                      "Run /auth, then update GOOGLE_REFRESH_TOKEN in Vercel and redeploy.")
    return True


def resolve_task(intent: dict, items: list[dict]) -> int | None:
    idx = intent.get("index")
    if idx is not None:
        i = int(idx) - 1
        return i if 0 <= i < len(items) else None
    title = (intent.get("title") or "").lower()
    if title:
        for i, t in enumerate(items):
            if title in t["title"].lower():
                return i
    return None


def do_task_add(chat_id: int, intent: dict):
    try:
        tasks.add(intent["title"], due=intent.get("due"), notes=intent.get("notes", ""))
    except Exception as e:
        if _needs_reauth(chat_id, e):
            return
        raise
    due = f"\nDue {intent['due']}" if intent.get("due") else ""
    # Tasks has no time of day, so anything the user said about one lives in notes.
    note = f"\nNote: {intent['notes']}" if intent.get("notes") else ""
    send(chat_id, f"Task added\n\n{intent['title']}{due}{note}")


def do_tasks(chat_id: int, user_id: int):
    try:
        items = tasks.list_open()
    except Exception as e:
        if _needs_reauth(chat_id, e):
            return
        raise
    _tasks_cache[user_id] = items
    if not items:
        send(chat_id, "No open tasks.")
        return
    lines = ["Your tasks:\n"]
    for i, t in enumerate(items, 1):
        due = f"  (due {t['due']})" if t["due"] else ""
        lines.append(f"{i}. {t['title']}{due}")
    send(chat_id, "\n".join(lines))


def do_task_done(chat_id: int, user_id: int, intent: dict):
    try:
        items = _tasks_cache.get(user_id)
        if not items:
            # A recycled instance loses the cache; refetch rather than making the user run /tasks.
            items = tasks.list_open()
            _tasks_cache[user_id] = items
        idx = resolve_task(intent, items)
        if idx is None:
            send(chat_id, "Couldn't find that task. Use /tasks to see the list.")
            return
        task = items[idx]
        tasks.complete(task["id"])
    except Exception as e:
        if _needs_reauth(chat_id, e):
            return
        raise
    _tasks_cache[user_id] = [t for t in items if t["id"] != task["id"]]
    send(chat_id, f"Done: {task['title']}")


def send_daily_digest():
    owner = int(os.environ.get("AUTHORIZED_USER_ID") or "0")
    if not owner:
        logger.error("AUTHORIZED_USER_ID is not set — nobody to send the digest to")
        return
    tz = os.environ.get("TIMEZONE", "UTC")
    today = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    due = tasks.due_today(today)
    if not due:
        return  # Silent by design — no message on a clear day.
    lines = ["Due today:\n"]
    for i, t in enumerate(due, 1):
        overdue = "  (overdue)" if t["due"] and t["due"] < today else ""
        lines.append(f"{i}. {t['title']}{overdue}")
    send(owner, "\n".join(lines))


def attach_zoom(intent: dict) -> str:
    """Book a Zoom meeting and fold the link into the event. Returns a line for the reply."""
    if not intent.get("zoom"):
        return ""
    try:
        meeting = zoom.create_meeting(
            intent["title"],
            intent["start_datetime"],
            duration_minutes(intent["start_datetime"], intent["end_datetime"]),
            os.environ.get("TIMEZONE", "UTC"),
        )
    except ZoomNotConfigured:
        return "\n\nZoom isn't configured — event added without a link."
    except Exception:
        # A missing video link must never cost the calendar entry.
        logger.exception("zoom meeting creation failed")
        return "\n\nCouldn't create the Zoom meeting — event added without a link."

    link = meeting["join_url"]
    intent["location"] = link
    description = (intent.get("description") or "").strip()
    intent["description"] = f"{description}\n\nZoom: {link}".strip()
    return f"\n\nZoom: {link}"


def attach_invites(intent: dict) -> str:
    """Resolve invite names to contact emails. Returns a line for the reply."""
    names = intent.get("invite") or []
    if not names:
        return ""
    try:
        result = contacts.resolve(names)
    except Exception:
        # Emailing nobody is recoverable; losing the event is not.
        logger.exception("contact lookup failed")
        return "\n\nCouldn't look up contacts — nobody was invited."

    if result["emails"]:
        intent["attendees"] = result["emails"]

    lines = []
    for m in result["matched"]:
        lines.append(f"Invited {m['count']} from \"{m['name']}\""
                     if m["kind"] == "label" else f"Invited {m['name']}")
    lines.extend(result["problems"])
    return "\n\n" + "\n".join(lines) if lines else ""


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
        try:
            zoom_note = attach_zoom(intent)
            invite_note = attach_invites(intent)
            # Looked up before inserting, so the new event cannot match itself.
            conflicts = calendar.find_conflicts(intent)
            event = calendar.create_event(intent)
            start = intent["start_datetime"].replace("T", " ")[:16]
            recur = f"\nRepeats: {intent['recurrence']}" if intent.get("recurrence") else ""
            msg = f"Added!\n\n{intent['title']}\n{start}{recur}\n{event.get('htmlLink', '')}"
            msg += zoom_note
            msg += invite_note
            warning = format_conflicts(conflicts)
            if warning:
                msg += f"\n\n{warning}"
            send(chat_id, msg)
        except Exception:
            logger.exception("create_event failed")
            send(chat_id, "Failed to add event. Please try again.")

    elif t == "task_add":
        do_task_add(chat_id, intent)

    elif t == "task_list":
        do_tasks(chat_id, user_id)

    elif t == "task_done":
        do_task_done(chat_id, user_id, intent)

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
        try:
            body = gmail.get_body(e["id"])
            send(chat_id, f"From: {e['from']}\nSubject: {e['subject']}\n\n{body[:3000]}")
        except Exception:
            logger.exception("get_body failed")
            send(chat_id, "Failed to read email. Try again.")

    elif t == "email_reply":
        if not inbox:
            inbox = gmail.list_unread()
            _inbox_cache[user_id] = inbox
        idx = resolve_index(intent, inbox)
        if idx is None:
            send(chat_id, "Couldn't find that email. Try /inbox to refresh.")
            return
        e = inbox[idx]
        try:
            gmail.reply(e["id"], e["thread_id"], e["from"], e["subject"], intent.get("body", ""))
            send(chat_id, f"Replied to {sender_name(e['from'])}")
        except Exception:
            logger.exception("reply failed")
            send(chat_id, "Failed to send reply. Try again.")

    elif t == "email_send":
        try:
            gmail.send(intent["to"], intent["subject"], intent["body"])
            send(chat_id, f"Sent to {intent['to']}")
        except Exception:
            logger.exception("send failed")
            send(chat_id, "Failed to send email. Try again.")


def handle_text(chat_id: int, user_id: int, text: str):
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
             "Tasks:\n"
             "\u2022 /tasks \u2014 show open tasks\n"
             "\u2022 /done 2 \u2014 mark task #2 finished\n"
             "\u2022 Or: remind me to buy groceries Friday\n\n"
             "Commands: /auth /status /inbox /tasks")
    elif text == "/auth":
        send(chat_id, f"Authorize Google Calendar & Gmail:\n\n{calendar.get_auth_url()}")
    elif text == "/status":
        if calendar.is_authenticated():
            send(chat_id, "Google Calendar & Gmail are connected.")
        else:
            send(chat_id, "Not connected. Use /auth")
    elif text == "/inbox":
        do_inbox(chat_id, user_id)
    elif text == "/tasks":
        do_tasks(chat_id, user_id)
    elif text.startswith("/done"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].isdigit():
            send(chat_id, "Usage: /done <number>  e.g. /done 2")
            return
        do_task_done(chat_id, user_id, {"index": int(parts[1])})
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
        try:
            body = gmail.get_body(e["id"])
            send(chat_id, f"From: {e['from']}\nSubject: {e['subject']}\n\n{body[:3000]}")
        except Exception:
            logger.exception("get_body failed")
            send(chat_id, "Failed to read email. Try again.")
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
        try:
            gmail.reply(e["id"], e["thread_id"], e["from"], e["subject"], parts[2])
            send(chat_id, f"Replied to {sender_name(e['from'])}")
        except Exception:
            logger.exception("reply failed")
            send(chat_id, "Failed to send reply. Try again.")
    elif not text.startswith("/"):
        process_text(chat_id, user_id, text)


def handle_voice(chat_id: int, user_id: int, file_id: str):
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


@app.route("/api/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or data.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    chat_type = message.get("chat", {}).get("type", "private")
    is_group = chat_type in ("group", "supergroup")
    text = (message.get("text") or "").strip()
    voice = message.get("voice")

    print(f"[webhook] chat_id={chat_id} user_id={user_id} chat_type={chat_type} is_group={is_group} owner={OWNER_ID} has_text={bool(text)} has_voice={bool(voice)}", flush=True)

    # Always answer 200. Telegram redelivers any update that doesn't get a 2xx,
    # so an exception here turns one bad message into an infinite retry loop.
    if chat_id and (is_group or not OWNER_ID or user_id == OWNER_ID):
        try:
            if text:
                handle_text(chat_id, user_id, text)
            elif voice:
                handle_voice(chat_id, user_id, voice["file_id"])
            elif message.get("audio") or message.get("document"):
                send(chat_id, "Please send a voice message (hold mic button in Telegram).")
        except Exception as e:
            logger.exception("update handling failed")
            try:
                send(chat_id, f"Something went wrong: {type(e).__name__}: {e}")
            except Exception:
                logger.exception("failed to notify user")

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
                f"{TG_API}/sendMessage",
                json={
                    "chat_id": OWNER_ID,
                    "text": (
                        "Google Calendar connected!\n\n"
                        "Add this in Vercel → Settings → Environment Variables:\n\n"
                        f"GOOGLE_REFRESH_TOKEN={refresh_token}\n\n"
                        "Then redeploy. You only need to do this once."
                    ),
                },
                timeout=10,
            )
        return "<h2>Connected!</h2><p>Check Telegram for next steps.</p>"
    return "<h2>Failed.</h2><p>Try /auth again in Telegram.</p>", 400


@app.route("/api/cron")
def cron():
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:
        # Fail closed: an unset secret would leave this endpoint open to anyone.
        logger.error("CRON_SECRET is not set — refusing to run the digest")
        return "CRON_SECRET not configured", 503
    if request.headers.get("Authorization") != f"Bearer {secret}":
        return "unauthorized", 401
    try:
        send_daily_digest()
    except Exception:
        logger.exception("daily digest failed")
    return "OK"


@app.route("/health")
def health():
    return "OK"
