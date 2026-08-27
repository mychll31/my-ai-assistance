"""Google Tasks: capture, review, and complete — all against the default task list."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tasks_service
from tasks_service import TasksService


def service_with(google=None):
    """A TasksService wired to a fake Google client."""
    auth = mock.MagicMock()
    auth.creds = mock.MagicMock(valid=True)
    svc = TasksService(auth)
    google = google or mock.MagicMock()
    return svc, google, mock.patch.object(tasks_service, "build", return_value=google)


def listing(*items):
    google = mock.MagicMock()
    google.tasks.return_value.list.return_value.execute.return_value = {"items": list(items)}
    return google


def test_add_targets_the_default_task_list():
    svc, google, patched = service_with()
    with patched:
        svc.add("Buy groceries")

    assert google.tasks.return_value.insert.call_args.kwargs["tasklist"] == "@default"


def test_add_normalizes_a_due_date_to_midnight_utc():
    """Tasks only stores a date; Google still demands a full RFC3339 timestamp."""
    svc, google, patched = service_with()
    with patched:
        svc.add("Buy groceries", due="2026-09-07")

    body = google.tasks.return_value.insert.call_args.kwargs["body"]
    assert body["due"] == "2026-09-07T00:00:00.000Z"


def test_add_omits_due_entirely_when_there_is_no_deadline():
    """Sending due=None makes the API reject the insert."""
    svc, google, patched = service_with()
    with patched:
        svc.add("Buy groceries")

    assert "due" not in google.tasks.return_value.insert.call_args.kwargs["body"]


def test_list_open_asks_google_to_leave_out_completed_tasks():
    svc, google, patched = service_with(listing())
    with patched:
        svc.list_open()

    assert google.tasks.return_value.list.call_args.kwargs["showCompleted"] is False


def test_list_open_drops_completed_and_deleted_items_google_still_returns():
    google = listing(
        {"id": "1", "title": "Open one"},
        {"id": "2", "title": "Done one", "status": "completed"},
        {"id": "3", "title": "Gone one", "deleted": True},
    )
    svc, _, patched = service_with(google)
    with patched:
        assert [t["title"] for t in svc.list_open()] == ["Open one"]


def test_list_open_reports_due_as_a_plain_date():
    google = listing({"id": "1", "title": "Buy groceries", "due": "2026-09-07T00:00:00.000Z"})
    svc, _, patched = service_with(google)
    with patched:
        assert svc.list_open()[0]["due"] == "2026-09-07"


def test_complete_patches_the_task_to_completed():
    svc, google, patched = service_with()
    with patched:
        svc.complete("task-abc")

    kwargs = google.tasks.return_value.patch.call_args.kwargs
    assert kwargs["task"] == "task-abc"
    assert kwargs["body"] == {"status": "completed"}


def test_due_today_includes_tasks_that_are_already_overdue():
    google = listing(
        {"id": "1", "title": "Yesterday's thing", "due": "2026-09-06T00:00:00.000Z"},
        {"id": "2", "title": "Today's thing", "due": "2026-09-07T00:00:00.000Z"},
    )
    svc, _, patched = service_with(google)
    with patched:
        assert [t["title"] for t in svc.due_today("2026-09-07")] == [
            "Yesterday's thing", "Today's thing"]


def test_due_today_excludes_future_and_undated_tasks():
    google = listing(
        {"id": "1", "title": "Next week", "due": "2026-09-14T00:00:00.000Z"},
        {"id": "2", "title": "Someday"},
    )
    svc, _, patched = service_with(google)
    with patched:
        assert svc.due_today("2026-09-07") == []


# --- how the bot behaves in Telegram -----------------------------------------
# Vercel serves app.py (Flask); api/webhook.py is the http.server variant.
# Both are exercised so the two cannot drift apart again.

import pytest
from googleapiclient.errors import HttpError

MODULES = ["app", "api.webhook"]


def load(name):
    import importlib
    return importlib.import_module(name)


def call_handle_text(mod, chat_id, user_id, text):
    if hasattr(mod, "handle_text"):
        mod.handle_text(chat_id, user_id, text)
    else:
        mod.handler._handle_text(object.__new__(mod.handler), chat_id, user_id, text)


def fake_tasks(open_tasks=()):
    t = mock.MagicMock()
    t.list_open.return_value = list(open_tasks)
    return t


def drive(modname, text, intent=None, open_tasks=(), cache=None, tasks_stub=None):
    """Run one message through a module, return (messages_sent, tasks_service)."""
    mod = load(modname)
    sent = []
    cal = mock.MagicMock()
    cal.is_authenticated.return_value = True
    tsk = tasks_stub or fake_tasks(open_tasks)

    with mock.patch.object(mod, "calendar", cal), \
         mock.patch.object(mod, "tasks", tsk), \
         mock.patch.object(mod, "send", lambda chat_id, msg: sent.append(msg)), \
         mock.patch.object(mod, "parse_intent", return_value=intent), \
         mock.patch.dict(mod._tasks_cache, cache or {}, clear=True):
        call_handle_text(mod, 1, 1, text)

    return sent, tsk


@pytest.mark.parametrize("modname", MODULES)
def test_adding_a_task_confirms_it_as_a_task_not_an_event(modname):
    """The LLM decides task-vs-event, so the reply must make the choice visible."""
    sent, tsk = drive(modname, "buy groceries friday",
                      intent={"type": "task_add", "title": "Buy groceries", "due": "2026-09-07"})

    assert tsk.add.call_args.kwargs["due"] == "2026-09-07"
    assert "Task added" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_tasks_command_numbers_the_open_tasks(modname):
    sent, _ = drive(modname, "/tasks", open_tasks=[
        {"id": "a", "title": "Buy groceries", "due": "2026-09-07"},
        {"id": "b", "title": "Call the bank", "due": None},
    ])

    assert "1. Buy groceries" in sent[-1]
    assert "2. Call the bank" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_tasks_command_says_so_when_the_list_is_empty(modname):
    sent, _ = drive(modname, "/tasks", open_tasks=[])
    assert "No open tasks" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_done_by_number_completes_that_task(modname):
    warm = [{"id": "a", "title": "Buy groceries", "due": None},
            {"id": "b", "title": "Call the bank", "due": None}]
    sent, tsk = drive(modname, "/done 2", open_tasks=warm, cache={1: warm})

    assert tsk.complete.call_args.args[0] == "b"
    assert "Call the bank" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_done_refetches_when_the_cache_was_lost_to_a_cold_instance(modname):
    """Serverless instances get recycled; /done must not depend on a warm cache."""
    sent, tsk = drive(modname, "/done 1",
                      open_tasks=[{"id": "a", "title": "Buy groceries", "due": None}])

    assert tsk.list_open.called, "should refetch instead of asking the user to run /tasks"
    assert tsk.complete.call_args.args[0] == "a"


@pytest.mark.parametrize("modname", MODULES)
def test_done_by_name_completes_the_matching_task(modname):
    sent, tsk = drive(modname, "finished the groceries",
                      intent={"type": "task_done", "index": None, "title": "groceries"},
                      open_tasks=[{"id": "a", "title": "Buy groceries", "due": None}])

    assert tsk.complete.call_args.args[0] == "a"


@pytest.mark.parametrize("modname", MODULES)
def test_a_token_predating_the_tasks_scope_is_reported_as_needing_reauth(modname):
    tsk = fake_tasks()
    tsk.list_open.side_effect = HttpError(
        mock.MagicMock(status=403), b'{"error":{"message":"insufficient authentication scopes"}}')

    sent, _ = drive(modname, "/tasks", tasks_stub=tsk)

    assert any("/auth" in m for m in sent), f"got {sent}"


# --- the daily digest, served by the Flask app Vercel actually runs -----------

def run_cron(auth_header=None, secret="s3cret", due=()):
    import app as a

    sent = []
    tsk = mock.MagicMock()
    tsk.due_today.return_value = list(due)

    env = {"TIMEZONE": "Asia/Manila", "AUTHORIZED_USER_ID": "42",
           "CRON_SECRET": secret if secret is not None else ""}

    with mock.patch.dict(os.environ, env), \
         mock.patch.object(a, "tasks", tsk), \
         mock.patch.object(a, "send", lambda chat_id, msg: sent.append(msg)):
        headers = {"Authorization": auth_header} if auth_header else {}
        resp = a.app.test_client().get("/api/cron", headers=headers)

    return resp.status_code, sent


def test_digest_rejects_a_caller_without_the_cron_secret():
    """The URL is public; without this anyone could spam the digest."""
    status, sent = run_cron(auth_header=None)

    assert status == 401
    assert sent == []


def test_digest_refuses_to_run_when_no_secret_is_configured():
    """Fail closed — an unset secret must not mean an open endpoint."""
    status, sent = run_cron(auth_header="Bearer anything", secret=None)

    assert status == 503
    assert sent == []


def test_digest_stays_silent_when_nothing_is_due():
    status, sent = run_cron(auth_header="Bearer s3cret", due=[])

    assert status == 200
    assert sent == []


def test_digest_lists_what_is_due_today():
    status, sent = run_cron(auth_header="Bearer s3cret", due=[
        {"id": "a", "title": "Buy groceries", "due": "2026-09-07"},
        {"id": "b", "title": "Call the bank", "due": "2026-09-06"},
    ])

    assert status == 200
    assert "Buy groceries" in sent[-1]
    assert "Call the bank" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_a_disabled_tasks_api_is_not_reported_as_a_token_problem(modname):
    """Both faults are 403; telling the user to re-auth for a disabled API wastes their time."""
    tsk = fake_tasks()
    tsk.list_open.side_effect = HttpError(
        mock.MagicMock(status=403),
        b'{"error":{"code":403,"message":"Google Tasks API has not been used in project '
        b'386693840120 before or it is disabled.","errors":[{"reason":"accessNotConfigured"}]}}')

    sent, _ = drive(modname, "/tasks", tasks_stub=tsk)

    assert "Tasks API" in sent[-1]
    assert "/auth" not in sent[-1], "re-authorizing cannot fix a disabled API"


@pytest.mark.parametrize("modname", MODULES)
def test_task_keeps_a_time_of_day_that_tasks_cannot_store(modname):
    """"Remind me ... at 1pm" is a task, but the 1pm must not vanish silently."""
    sent, tsk = drive(modname, "remind me to check the evaluation tomorrow at 1pm",
                      intent={"type": "task_add", "title": "Check the evaluation",
                              "due": "2026-08-28", "notes": "1pm"})

    assert tsk.add.call_args.kwargs["notes"] == "1pm"
    assert "1pm" in sent[-1], "the dropped time must still be visible to the user"
