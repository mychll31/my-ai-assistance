import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic

client = Anthropic()

_PROMPT = """You are a personal assistant bot. Classify the user's message as one of these intents and return ONLY a JSON object — no other text.

Current time: {now} (timezone: {timezone})

Intents and their JSON shapes:

CALENDAR — schedule or create a calendar event:
{{"type":"calendar","title":"...","start_datetime":"YYYY-MM-DDTHH:MM:SS","end_datetime":"YYYY-MM-DDTHH:MM:SS","description":"","location":""}}

EMAIL_LIST — check inbox / show unread emails:
{{"type":"email_list"}}

EMAIL_READ — read a specific email (by number or sender name):
{{"type":"email_read","index":null,"sender_name":null}}

EMAIL_REPLY — reply to an email:
{{"type":"email_reply","index":null,"sender_name":null,"body":"..."}}

EMAIL_SEND — compose and send a new email:
{{"type":"email_send","to":"email@example.com","subject":"...","body":"..."}}

UNKNOWN — doesn't fit any above:
{{"type":"unknown"}}

Calendar rules:
- Default duration: 1 hour if not specified
- Default time: 09:00 if not specified
- Relative days (tomorrow, Friday, next week) use the next upcoming occurrence

{inbox_context}Message: {message}"""


def parse_intent(message: str, timezone: str = "UTC", inbox: list[dict] | None = None) -> dict | None:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz).strftime("%A, %B %d, %Y %H:%M")

    if inbox:
        lines = ["Current inbox (use index numbers to identify emails):\n"]
        for i, e in enumerate(inbox, 1):
            lines.append(f"{i}. From: {e['from']} — Subject: {e['subject']}")
        inbox_context = "\n".join(lines) + "\n\n"
    else:
        inbox_context = ""

    prompt = _PROMPT.format(now=now, timezone=timezone, inbox_context=inbox_context, message=message)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None

    data = json.loads(match.group())
    return None if data.get("type") == "unknown" else data


def parse_event(message: str, timezone: str = "UTC") -> dict | None:
    """Legacy wrapper — returns calendar event dict or None."""
    result = parse_intent(message, timezone)
    if result and result.get("type") == "calendar":
        return result
    return None
