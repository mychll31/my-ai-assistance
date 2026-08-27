"""Zoom meetings are created only on request, and never at the cost of the calendar event."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import zoom_service
from zoom_service import ZoomNotConfigured, ZoomService, duration_minutes

CREDS = {"ZOOM_ACCOUNT_ID": "acct-1", "ZOOM_CLIENT_ID": "cid", "ZOOM_CLIENT_SECRET": "sek"}


def responses(*payloads):
    """A stand-in for requests.post returning each payload in turn."""
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        r = mock.MagicMock()
        r.json.return_value = payloads[min(len(calls) - 1, len(payloads) - 1)]
        r.raise_for_status.return_value = None
        return r

    return post, calls


TOKEN = {"access_token": "tok-abc", "expires_in": 3600}
MEETING = {"id": 987, "join_url": "https://zoom.us/j/987", "password": "pw"}


def test_token_request_uses_the_account_credentials_grant():
    post, calls = responses(TOKEN)
    with mock.patch.dict(os.environ, CREDS), mock.patch.object(zoom_service.http, "post", post):
        ZoomService()._access_token()

    url, kw = calls[0]
    assert url == "https://zoom.us/oauth/token"
    assert kw["params"] == {"grant_type": "account_credentials", "account_id": "acct-1"}


def test_token_request_authenticates_with_basic_client_credentials():
    post, calls = responses(TOKEN)
    with mock.patch.dict(os.environ, CREDS), mock.patch.object(zoom_service.http, "post", post):
        ZoomService()._access_token()

    import base64
    expected = base64.b64encode(b"cid:sek").decode()
    assert calls[0][1]["headers"]["Authorization"] == f"Basic {expected}"


def test_a_valid_token_is_reused_instead_of_refetched():
    post, calls = responses(TOKEN, MEETING)
    with mock.patch.dict(os.environ, CREDS), mock.patch.object(zoom_service.http, "post", post):
        z = ZoomService()
        z._access_token(now=1000)
        z._access_token(now=1500)

    assert len([c for c in calls if "oauth" in c[0]]) == 1


def test_an_expired_token_is_refetched():
    post, calls = responses(TOKEN)
    with mock.patch.dict(os.environ, CREDS), mock.patch.object(zoom_service.http, "post", post):
        z = ZoomService()
        z._access_token(now=1000)
        z._access_token(now=1000 + 3600)  # past the early-renewal margin

    assert len([c for c in calls if "oauth" in c[0]]) == 2


def test_missing_credentials_raise_rather_than_calling_zoom():
    post, calls = responses(TOKEN)
    with mock.patch.dict(os.environ, {k: "" for k in CREDS}), \
         mock.patch.object(zoom_service.http, "post", post):
        with pytest.raises(ZoomNotConfigured):
            ZoomService()._access_token()

    assert calls == []


def test_create_meeting_books_a_scheduled_meeting_at_the_event_time():
    post, calls = responses(TOKEN, MEETING)
    with mock.patch.dict(os.environ, CREDS), mock.patch.object(zoom_service.http, "post", post):
        ZoomService().create_meeting("Sync with Belle", "2026-08-28T15:00:00", 60, "Asia/Manila")

    url, kw = calls[-1]
    assert url == "https://api.zoom.us/v2/users/me/meetings"
    assert kw["json"] == {"topic": "Sync with Belle", "type": 2,
                          "start_time": "2026-08-28T15:00:00",
                          "duration": 60, "timezone": "Asia/Manila"}


def test_create_meeting_returns_the_join_url():
    post, _ = responses(TOKEN, MEETING)
    with mock.patch.dict(os.environ, CREDS), mock.patch.object(zoom_service.http, "post", post):
        assert ZoomService().create_meeting("x", "2026-08-28T15:00:00", 60, "UTC")["join_url"] \
            == "https://zoom.us/j/987"


def test_duration_comes_from_the_events_own_span():
    assert duration_minutes("2026-08-28T15:00:00", "2026-08-28T16:30:00") == 90


def test_a_zero_length_event_still_books_a_real_meeting():
    """Zoom rejects duration 0."""
    assert duration_minutes("2026-08-28T15:00:00", "2026-08-28T15:00:00") >= 1


# --- wiring: Vercel runs app.py, api/webhook.py is the http.server twin -------

MODULES = ["app", "api.webhook"]


def drive(modname, intent, zoom_stub=None):
    """Run one calendar intent through a module; return (messages, calendar, zoom)."""
    import importlib
    mod = importlib.import_module(modname)

    sent = []
    cal = mock.MagicMock()
    cal.is_authenticated.return_value = True
    cal.find_conflicts.return_value = []
    cal.create_event.return_value = {"htmlLink": "https://cal/x"}
    zm = zoom_stub or mock.MagicMock()
    zm.create_meeting.return_value = MEETING

    with mock.patch.object(mod, "calendar", cal), \
         mock.patch.object(mod, "zoom", zm), \
         mock.patch.object(mod, "send", lambda chat_id, msg: sent.append(msg)), \
         mock.patch.object(mod, "parse_intent", return_value=intent):
        mod.process_text(1, 1, "whatever")

    return sent, cal, zm


def calendar_intent(**over):
    base = {"type": "calendar", "title": "Sync with Belle",
            "start_datetime": "2026-08-28T15:00:00",
            "end_datetime": "2026-08-28T16:00:00",
            "description": "", "location": "", "recurrence": None}
    base.update(over)
    return base


@pytest.mark.parametrize("modname", MODULES)
def test_a_plain_event_never_books_a_zoom_meeting(modname):
    """Every booking is real and costs an entry on the Zoom account."""
    sent, cal, zm = drive(modname, calendar_intent())

    assert not zm.create_meeting.called
    assert cal.create_event.called
    assert "zoom" not in sent[-1].lower()


@pytest.mark.parametrize("modname", MODULES)
def test_a_zoom_event_puts_the_join_link_on_the_event_and_in_the_reply(modname):
    sent, cal, zm = drive(modname, calendar_intent(zoom=True))

    body = cal.create_event.call_args.args[0]
    assert body["location"] == "https://zoom.us/j/987"
    assert "https://zoom.us/j/987" in body["description"]
    assert "https://zoom.us/j/987" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_a_zoom_failure_still_creates_the_calendar_event(modname):
    zm = mock.MagicMock()
    zm.create_meeting.side_effect = RuntimeError("zoom is down")

    sent, cal, _ = drive(modname, calendar_intent(zoom=True), zoom_stub=zm)

    assert cal.create_event.called, "losing the event over a failed video link is worse"
    assert "Added!" in sent[-1]
    assert "couldn't create the zoom meeting" in sent[-1].lower()


@pytest.mark.parametrize("modname", MODULES)
def test_unconfigured_zoom_is_reported_as_such_not_as_a_crash(modname):
    zm = mock.MagicMock()
    zm.create_meeting.side_effect = ZoomNotConfigured("nope")

    sent, cal, _ = drive(modname, calendar_intent(zoom=True), zoom_stub=zm)

    assert cal.create_event.called
    assert "isn't configured" in sent[-1].lower()
