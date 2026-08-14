import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo


def _call_llm(prompt: str) -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic
        response = Anthropic().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        response = OpenAI().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=512,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()
    if os.environ.get("GROQ_API_KEY"):
        # Groq is OpenAI-compatible, so the same client works against their base URL.
        # Model is overridable — Groq retires model IDs periodically.
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )
        response = client.chat.completions.create(
            model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            max_tokens=512,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip()
    raise RuntimeError(
        "No LLM key set — provide ANTHROPIC_API_KEY, OPENAI_API_KEY or GROQ_API_KEY"
    )

_PROMPT = """You are a personal assistant bot. Classify the user's message as one of these intents and return ONLY a JSON object — no other text.

Current time: {now} (timezone: {timezone})

Intents and their JSON shapes:

CALENDAR — schedule or create a calendar event:
{{"type":"calendar","title":"...","start_datetime":"YYYY-MM-DDTHH:MM:SS","end_datetime":"YYYY-MM-DDTHH:MM:SS","description":"","location":"","recurrence":null}}

recurrence must be a valid RRULE string (RFC 5545) or null. Examples:
- "every Monday" → "RRULE:FREQ=WEEKLY;BYDAY=MO"
- "every weekday" → "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
- "every day" → "RRULE:FREQ=DAILY"
- "every month on the 1st" → "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
- "every year" → "RRULE:FREQ=YEARLY"
- one-time event → null

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

    text = _call_llm(prompt)
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
