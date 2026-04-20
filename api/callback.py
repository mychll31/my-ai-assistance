import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as http
from calendar_service import CalendarService

calendar = CalendarService()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("AUTHORIZED_USER_ID") or "0")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        code = (params.get("code") or [None])[0]
        state = (params.get("state") or [None])[0]

        if not code:
            self._respond(400, b"<h2>Missing code.</h2>")
            return

        refresh_token = calendar.handle_callback(code, state=state)
        if refresh_token:
            if OWNER_ID and BOT_TOKEN:
                http.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
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
            self._respond(200, b"<h2>Connected!</h2><p>Check Telegram for next steps.</p>")
        else:
            self._respond(400, b"<h2>Failed.</h2><p>Try /auth again in Telegram.</p>")

    def _respond(self, code: int, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
