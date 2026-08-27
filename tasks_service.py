import logging

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Named lists would need the parser to route by list name; @default keeps that
# guesswork out and matches what the Tasks app opens on.
_LIST = "@default"


def _due_rfc3339(due: str) -> str:
    """Tasks stores a date but the API insists on a full timestamp, then drops the time."""
    return f"{due[:10]}T00:00:00.000Z"


class TasksService:
    def __init__(self, auth_service):
        self._auth = auth_service  # shares CalendarService credentials

    def _svc(self):
        creds = self._auth.creds
        if not creds.valid:
            creds.refresh(Request())
            self._auth._save()
        return build("tasks", "v1", credentials=creds)

    def add(self, title: str, due: str | None = None, notes: str = "") -> dict:
        body = {"title": title}
        if notes:
            body["notes"] = notes
        if due:
            body["due"] = _due_rfc3339(due)
        return self._svc().tasks().insert(tasklist=_LIST, body=body).execute()

    def list_open(self, max_results: int = 20) -> list[dict]:
        result = self._svc().tasks().list(
            tasklist=_LIST, showCompleted=False, maxResults=max_results,
        ).execute()
        tasks = []
        for t in result.get("items", []):
            # showCompleted should cover this, but a stale item slipping through
            # would show up as an already-done task in the digest.
            if t.get("status") == "completed" or t.get("deleted"):
                continue
            tasks.append({
                "id": t["id"],
                "title": t.get("title") or "(untitled)",
                "due": (t.get("due") or "")[:10] or None,
            })
        return tasks

    def complete(self, task_id: str) -> dict:
        return self._svc().tasks().patch(
            tasklist=_LIST, task=task_id, body={"status": "completed"},
        ).execute()

    def due_today(self, today: str) -> list[dict]:
        """Open tasks due today or already overdue. `today` is YYYY-MM-DD."""
        return [t for t in self.list_open() if t["due"] and t["due"] <= today]
