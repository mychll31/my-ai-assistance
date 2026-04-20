import json
import logging
import os
import urllib.parse
from pathlib import Path

import requests as http
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

TOKEN_FILE = Path(os.environ.get("DATA_DIR", "./data")) / "tokens.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.modify",
]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class CalendarService:
    def __init__(self):
        self.creds: Credentials | None = None
        self._load()

    def _load(self):
        # Env var takes priority — works on platforms without persistent volumes (e.g. DO App Platform)
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
        if refresh_token:
            self.creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                scopes=SCOPES,
            )
            return
        # Fallback: file storage (Fly.io volumes, local dev, Droplet)
        if TOKEN_FILE.exists():
            data = json.loads(TOKEN_FILE.read_text())
            self.creds = Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                scopes=SCOPES,
            )

    def _save(self):
        try:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(json.dumps({
                "token": self.creds.token,
                "refresh_token": self.creds.refresh_token,
            }))
        except OSError:
            pass  # No volume mounted — token is stored via GOOGLE_REFRESH_TOKEN env var instead

    def is_authenticated(self) -> bool:
        if not self.creds:
            return False
        if not self.creds.valid:
            if not self.creds.refresh_token:
                return False
            try:
                self.creds.refresh(Request())
                self._save()
            except Exception as e:
                logger.error(f"Token refresh failed: {e}")
                return False
        return True

    def get_auth_url(self) -> str:
        # Build auth URL manually — avoids PKCE which breaks stateless serverless callbacks
        params = {
            "response_type": "code",
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "redirect_uri": os.environ["OAUTH_REDIRECT_URI"],
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{_AUTH_URI}?{urllib.parse.urlencode(params)}"

    def handle_callback(self, code: str, state: str = None) -> str | None:
        """Returns the refresh token on success, None on failure."""
        try:
            resp = http.post(_TOKEN_URI, data={
                "code": code,
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri": os.environ["OAUTH_REDIRECT_URI"],
                "grant_type": "authorization_code",
            }, timeout=15)
            data = resp.json()
            if "error" in data:
                logger.error(f"Token exchange error: {data}")
                return None
            self.creds = Credentials(
                token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                token_uri=_TOKEN_URI,
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                scopes=SCOPES,
            )
            self._save()
            return data.get("refresh_token")
        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            return None

    def create_event(self, event_data: dict) -> dict:
        if not self.creds.valid:
            self.creds.refresh(Request())
            self._save()
        service = build("calendar", "v3", credentials=self.creds)
        tz = os.environ.get("TIMEZONE", "UTC")
        body = {
            "summary": event_data["title"],
            "description": event_data.get("description", ""),
            "location": event_data.get("location", ""),
            "start": {"dateTime": event_data["start_datetime"], "timeZone": tz},
            "end": {"dateTime": event_data["end_datetime"], "timeZone": tz},
        }
        if event_data.get("recurrence"):
            body["recurrence"] = [event_data["recurrence"]]
        return service.events().insert(calendarId="primary", body=body).execute()
