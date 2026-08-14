"""The webhook must always answer 200, or Telegram redelivers the update forever."""
import io
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api.webhook as w


def run_update(payload: dict) -> list[int]:
    """Drive handler.do_POST with a fake socket, return the status codes it sent."""
    handler = object.__new__(w.handler)
    raw = json.dumps(payload).encode()
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.headers = {"Content-Length": str(len(raw))}

    statuses: list[int] = []
    handler.send_response = statuses.append
    handler.send_header = lambda *a, **k: None
    handler.end_headers = lambda: None

    w.handler.do_POST(handler)
    return statuses


TEXT_UPDATE = {
    "message": {
        "chat": {"id": 1, "type": "private"},
        "from": {"id": 1},
        "text": "Set event tomorrow 1pm clinic",
    }
}


def test_returns_200_when_processing_raises():
    """A crash in process_text must not cost us the 200 — that is what caused the loop."""
    boom = mock.patch.object(w, "process_text", side_effect=RuntimeError("No LLM key set"))
    with boom, mock.patch.object(w, "send"):
        statuses = run_update(TEXT_UPDATE)

    assert statuses == [200], f"expected a 200 despite the crash, got {statuses}"


def test_notifies_user_when_processing_raises():
    """Silent failure is why this took a screenshot to notice."""
    boom = mock.patch.object(w, "process_text", side_effect=RuntimeError("No LLM key set"))
    with boom, mock.patch.object(w, "send") as send:
        run_update(TEXT_UPDATE)

    assert send.called, "user was told nothing when the update failed"


def test_returns_200_on_normal_update():
    with mock.patch.object(w, "process_text"), mock.patch.object(w, "send"):
        assert run_update(TEXT_UPDATE) == [200]
