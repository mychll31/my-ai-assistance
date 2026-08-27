import base64
import logging
import os
import time
from datetime import datetime

import requests as http

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://zoom.us/oauth/token"
_API = "https://api.zoom.us/v2"
_CREDS = ("ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET")


class ZoomNotConfigured(RuntimeError):
    """Raised instead of calling Zoom when the credentials aren't set."""


def duration_minutes(start_datetime: str, end_datetime: str) -> int:
    start = datetime.fromisoformat(start_datetime)
    end = datetime.fromisoformat(end_datetime)
    # Zoom rejects a zero-length meeting, so never go below one minute.
    return max(1, int((end - start).total_seconds() // 60))


class ZoomService:
    def __init__(self):
        self._cached: tuple[str, float] | None = None

    def is_configured(self) -> bool:
        return all(os.environ.get(k) for k in _CREDS)

    def _access_token(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        if self._cached and self._cached[1] > now:
            return self._cached[0]
        if not self.is_configured():
            raise ZoomNotConfigured("ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET must be set")

        basic = base64.b64encode(
            f"{os.environ['ZOOM_CLIENT_ID']}:{os.environ['ZOOM_CLIENT_SECRET']}".encode()
        ).decode()
        r = http.post(
            _TOKEN_URL,
            params={"grant_type": "account_credentials",
                    "account_id": os.environ["ZOOM_ACCOUNT_ID"]},
            headers={"Authorization": f"Basic {basic}"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        # Renew a minute early so a token can't expire mid-request.
        self._cached = (data["access_token"], now + int(data.get("expires_in", 3600)) - 60)
        return self._cached[0]

    def create_meeting(self, topic: str, start_datetime: str, duration: int, timezone: str) -> dict:
        """type 2 is a one-off scheduled meeting. start_datetime is local to `timezone`."""
        r = http.post(
            f"{_API}/users/me/meetings",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json={"topic": topic, "type": 2, "start_time": start_datetime,
                  "duration": duration, "timezone": timezone},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        return {"join_url": data["join_url"], "id": data.get("id"),
                "password": data.get("password")}
