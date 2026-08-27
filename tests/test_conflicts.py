"""A new event must warn about existing events it overlaps — without ever blocking creation."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calendar_service
from calendar_service import CalendarService, format_conflicts

NEW_EVENT = {
    "title": "Meeting with Belle",
    "start_datetime": "2026-08-28T15:00:00",
    "end_datetime": "2026-08-28T16:00:00",
}


def service_returning(*items):
    """A CalendarService whose Google lookup yields the given event resources."""
    svc = object.__new__(CalendarService)
    svc.creds = mock.MagicMock(valid=True)

    google = mock.MagicMock()
    google.events.return_value.list.return_value.execute.return_value = {"items": list(items)}
    return svc, google, mock.patch.object(calendar_service, "build", return_value=google)


def timed(title, start, end, **extra):
    return {"summary": title, "start": {"dateTime": start}, "end": {"dateTime": end}, **extra}


def all_day(title, date, end_date):
    return {"summary": title, "start": {"date": date}, "end": {"date": end_date}}


def in_manila():
    return mock.patch.dict(os.environ, {"TIMEZONE": "Asia/Manila"})


def test_overlapping_event_is_reported_as_a_conflict():
    svc, _, patched = service_returning(
        timed("Team offsite", "2026-08-28T07:00:00+08:00", "2026-08-28T17:00:00+08:00")
    )
    with in_manila(), patched:
        conflicts = svc.find_conflicts(NEW_EVENT)

    assert [c["title"] for c in conflicts] == ["Team offsite"]


def test_query_window_is_exactly_the_new_event_span():
    """Widening the window past the event's own start/end would flag back-to-back events."""
    svc, google, patched = service_returning()
    with in_manila(), patched:
        svc.find_conflicts(NEW_EVENT)

    kwargs = google.events.return_value.list.call_args.kwargs
    assert kwargs["timeMin"] == "2026-08-28T15:00:00+08:00"
    assert kwargs["timeMax"] == "2026-08-28T16:00:00+08:00"


def test_recurring_events_are_expanded_into_instances():
    """Without singleEvents a weekly standup is one resource at its original date, not that day's copy."""
    svc, google, patched = service_returning()
    with in_manila(), patched:
        svc.find_conflicts(NEW_EVENT)

    assert google.events.return_value.list.call_args.kwargs["singleEvents"] is True


def test_all_day_event_is_reported_as_a_conflict():
    svc, _, patched = service_returning(all_day("Out of office", "2026-08-28", "2026-08-29"))
    with in_manila(), patched:
        conflicts = svc.find_conflicts(NEW_EVENT)

    assert [(c["title"], c["all_day"]) for c in conflicts] == [("Out of office", True)]


def test_events_marked_free_are_not_conflicts():
    svc, _, patched = service_returning(
        timed("Gym", "2026-08-28T15:00:00+08:00", "2026-08-28T16:00:00+08:00",
              transparency="transparent")
    )
    with in_manila(), patched:
        assert svc.find_conflicts(NEW_EVENT) == []


def test_cancelled_events_are_not_conflicts():
    svc, _, patched = service_returning(
        timed("Dropped call", "2026-08-28T15:00:00+08:00", "2026-08-28T16:00:00+08:00",
              status="cancelled")
    )
    with in_manila(), patched:
        assert svc.find_conflicts(NEW_EVENT) == []


def test_lookup_failure_reports_no_conflicts_instead_of_raising():
    """A warning feature must never stop the event from being created."""
    svc = object.__new__(CalendarService)
    svc.creds = mock.MagicMock(valid=True)
    google = mock.MagicMock()
    google.events.return_value.list.return_value.execute.side_effect = RuntimeError("500")

    with in_manila(), mock.patch.object(calendar_service, "build", return_value=google):
        assert svc.find_conflicts(NEW_EVENT) == []


def test_format_conflicts_is_empty_when_there_are_none():
    assert format_conflicts([]) == ""


def test_format_conflicts_lists_each_conflict_with_its_time_range():
    text = format_conflicts([
        {"title": "Team offsite", "start": "2026-08-28T07:00:00+08:00",
         "end": "2026-08-28T17:00:00+08:00", "all_day": False},
    ])

    assert "Team offsite" in text
    assert "7:00 AM" in text and "5:00 PM" in text


def test_format_conflicts_labels_all_day_events_instead_of_showing_midnight():
    text = format_conflicts([
        {"title": "Out of office", "start": "2026-08-28", "end": "2026-08-29", "all_day": True},
    ])

    assert "Out of office" in text
    assert "all day" in text.lower()
    assert "12:00 AM" not in text


# --- the confirmation message the user actually sees -------------------------

CONFLICT = {"title": "Team offsite", "start": "2026-08-28T07:00:00+08:00",
            "end": "2026-08-28T17:00:00+08:00", "all_day": False}


def sent_messages(module, conflicts):
    """Drive the module's calendar branch and collect what it sends back."""
    sent = []
    fake_cal = mock.MagicMock()
    fake_cal.is_authenticated.return_value = True
    fake_cal.find_conflicts.return_value = conflicts
    fake_cal.create_event.return_value = {"htmlLink": "https://cal/x"}

    intent = dict(NEW_EVENT, type="calendar")
    with mock.patch.object(module, "calendar", fake_cal), \
         mock.patch.object(module, "send", lambda chat_id, text: sent.append(text)), \
         mock.patch.object(module, "parse_intent", return_value=intent):
        module.process_text(1, 1, "meeting with belle aug 28 3pm")

    return sent, fake_cal


def test_webhook_confirmation_warns_about_the_overlapping_event():
    import api.webhook as w
    sent, cal = sent_messages(w, [CONFLICT])

    assert cal.create_event.called, "the event must still be created"
    assert "Added!" in sent[-1]
    assert "Team offsite" in sent[-1]


def test_webhook_confirmation_stays_clean_when_nothing_overlaps():
    import api.webhook as w
    sent, _ = sent_messages(w, [])

    assert "Added!" in sent[-1]
    assert "Conflicts" not in sent[-1]


def test_flask_app_confirmation_warns_about_the_overlapping_event():
    import app
    sent, cal = sent_messages(app, [CONFLICT])

    assert cal.create_event.called
    assert "Team offsite" in sent[-1]
