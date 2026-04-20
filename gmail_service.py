import base64
import logging
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GmailService:
    def __init__(self, auth_service):
        self._auth = auth_service  # shares CalendarService credentials

    def _svc(self):
        creds = self._auth.creds
        if not creds.valid:
            creds.refresh(Request())
            self._auth._save()
        return build("gmail", "v1", credentials=creds)

    def list_unread(self, max_results: int = 5) -> list[dict]:
        svc = self._svc()
        result = svc.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results,
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            m = svc.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject"],
            ).execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "thread_id": m["threadId"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "snippet": m.get("snippet", ""),
            })
        return emails

    def get_body(self, message_id: str) -> str:
        svc = self._svc()
        m = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
        return _extract_body(m["payload"])

    def reply(self, message_id: str, thread_id: str, to: str, subject: str, body: str) -> dict:
        svc = self._svc()
        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return svc.users().messages().send(
            userId="me", body={"raw": raw, "threadId": thread_id},
        ).execute()

    def send(self, to: str, subject: str, body: str) -> dict:
        svc = self._svc()
        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return svc.users().messages().send(userId="me", body={"raw": raw}).execute()


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part["mimeType"] == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return ""
