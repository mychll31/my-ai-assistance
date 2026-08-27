"""Invitations email real people, so resolution is strict: contacts only, never a guess."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import contacts_service
from contacts_service import ContactsService

MARKETING = "contactGroups/mkt"
VALENIN = "contactGroups/val"


def group(resource, name, kind="USER_CONTACT_GROUP"):
    return {"resourceName": resource, "name": name, "groupType": kind}


def person(name, email=None, groups=()):
    p = {"resourceName": f"people/{name}", "names": [{"displayName": name}],
         "memberships": [{"contactGroupMembership": {"contactGroupResourceName": g}} for g in groups]}
    if email:
        p["emailAddresses"] = [{"value": email}]
    return p


def service(groups=(), people=()):
    google = mock.MagicMock()
    google.contactGroups.return_value.list.return_value.execute.return_value = {
        "contactGroups": list(groups)}
    google.people.return_value.connections.return_value.list.return_value.execute.return_value = {
        "connections": list(people)}
    auth = mock.MagicMock()
    auth.creds = mock.MagicMock(valid=True)
    return ContactsService(auth), mock.patch.object(contacts_service, "build", return_value=google)


DEFAULT_GROUPS = [group(MARKETING, "marketing"), group(VALENIN, "Valenin"),
                  group("contactGroups/myContacts", "myContacts", "SYSTEM_CONTACT_GROUP")]
DEFAULT_PEOPLE = [
    person("Maychell Alcorin", "mychll31@gmail.com", [MARKETING]),
    person("Ana Cruz", "ana@valenin.com", [VALENIN]),
    person("Ben Diaz", "ben@valenin.com", [VALENIN]),
]


def test_a_label_resolves_to_its_members_emails():
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE)
    with patched:
        r = svc.resolve(["Valenin"])

    assert sorted(r["emails"]) == ["ana@valenin.com", "ben@valenin.com"]
    assert r["problems"] == []


def test_a_label_matches_regardless_of_case():
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE)
    with patched:
        assert svc.resolve(["VALENIN"])["emails"]


def test_a_system_group_is_not_a_label():
    """"myContacts" is Google's own group and would invite the entire address book."""
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE)
    with patched:
        r = svc.resolve(["myContacts"])

    assert r["emails"] == []
    assert r["problems"]


def test_an_individual_contact_resolves_by_name():
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE)
    with patched:
        assert svc.resolve(["Ana"])["emails"] == ["ana@valenin.com"]


def test_a_name_that_is_not_a_contact_invites_nobody():
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE)
    with patched:
        r = svc.resolve(["markting"])

    assert r["emails"] == []
    assert any("markting" in p for p in r["problems"])


def test_a_contact_without_an_email_is_reported_not_silently_dropped():
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE + [person("Carl Reyes", None, [VALENIN])])
    with patched:
        r = svc.resolve(["Carl"])

    assert r["emails"] == []
    assert any("Carl" in p and "email" in p.lower() for p in r["problems"])


def test_an_ambiguous_name_invites_nobody_and_names_the_candidates():
    """Guessing between two people means emailing the wrong one."""
    people = DEFAULT_PEOPLE + [person("Ana Santos", "asantos@x.com", [VALENIN])]
    svc, patched = service(DEFAULT_GROUPS, people)
    with patched:
        r = svc.resolve(["Ana"])

    assert r["emails"] == []
    assert any("Ana Cruz" in p and "Ana Santos" in p for p in r["problems"])


def test_a_raw_email_address_is_never_invited():
    """Only people already in Contacts may be invited."""
    svc, patched = service(DEFAULT_GROUPS, DEFAULT_PEOPLE)
    with patched:
        r = svc.resolve(["stranger@example.com"])

    assert r["emails"] == []
    assert r["problems"]


def test_someone_in_two_matched_groups_is_only_invited_once():
    people = DEFAULT_PEOPLE + [person("Dee Lim", "dee@valenin.com", [MARKETING, VALENIN])]
    svc, patched = service(DEFAULT_GROUPS, people)
    with patched:
        r = svc.resolve(["marketing", "Valenin"])

    assert len(r["emails"]) == len(set(r["emails"]))
    assert "dee@valenin.com" in r["emails"]


# --- the event body itself -----------------------------------------------------

import calendar_service
from calendar_service import CalendarService

EVENT = {"title": "Team sync", "start_datetime": "2026-08-28T15:00:00",
         "end_datetime": "2026-08-28T16:00:00"}


def calendar_with():
    google = mock.MagicMock()
    svc = object.__new__(CalendarService)
    svc.creds = mock.MagicMock(valid=True)
    return svc, google, mock.patch.object(calendar_service, "build", return_value=google)


def test_attendees_are_put_on_the_event_and_google_is_told_to_email_them():
    svc, google, patched = calendar_with()
    with mock.patch.dict(os.environ, {"TIMEZONE": "Asia/Manila"}), patched:
        svc.create_event(dict(EVENT, attendees=["ana@valenin.com", "ben@valenin.com"]))

    kwargs = google.events.return_value.insert.call_args.kwargs
    assert kwargs["body"]["attendees"] == [{"email": "ana@valenin.com"}, {"email": "ben@valenin.com"}]
    assert kwargs["sendUpdates"] == "all", "without this Google adds them but emails nobody"


def test_an_event_with_no_attendees_notifies_nobody():
    svc, google, patched = calendar_with()
    with mock.patch.dict(os.environ, {"TIMEZONE": "Asia/Manila"}), patched:
        svc.create_event(dict(EVENT))

    kwargs = google.events.return_value.insert.call_args.kwargs
    assert "attendees" not in kwargs["body"]
    assert kwargs["sendUpdates"] == "none"


# --- wiring --------------------------------------------------------------------

MODULES = ["app", "api.webhook"]


def drive(modname, intent, contacts_stub=None):
    import importlib
    mod = importlib.import_module(modname)

    sent = []
    cal = mock.MagicMock()
    cal.is_authenticated.return_value = True
    cal.find_conflicts.return_value = []
    cal.create_event.return_value = {"htmlLink": "https://cal/x"}
    con = contacts_stub or mock.MagicMock()
    if contacts_stub is None:
        con.resolve.return_value = {"emails": ["ana@valenin.com", "ben@valenin.com"],
                                    "matched": [{"name": "Valenin", "kind": "label", "count": 2}],
                                    "problems": []}
    zm = mock.MagicMock()

    with mock.patch.object(mod, "calendar", cal), mock.patch.object(mod, "contacts", con), \
         mock.patch.object(mod, "zoom", zm), \
         mock.patch.object(mod, "send", lambda chat_id, msg: sent.append(msg)), \
         mock.patch.object(mod, "parse_intent", return_value=intent):
        mod.process_text(1, 1, "whatever")

    return sent, cal, con


def cal_intent(**over):
    base = {"type": "calendar", "title": "Team sync",
            "start_datetime": "2026-08-28T15:00:00", "end_datetime": "2026-08-28T16:00:00",
            "description": "", "location": "", "recurrence": None}
    base.update(over)
    return base


@pytest.mark.parametrize("modname", MODULES)
def test_an_event_without_invite_never_touches_contacts(modname):
    """Every invite emails real people; a plain event must not risk it."""
    sent, cal, con = drive(modname, cal_intent())

    assert not con.resolve.called
    assert cal.create_event.called
    assert "invited" not in sent[-1].lower()


@pytest.mark.parametrize("modname", MODULES)
def test_invited_emails_reach_the_event_and_the_reply_says_who(modname):
    sent, cal, con = drive(modname, cal_intent(invite=["Valenin"]))

    assert cal.create_event.call_args.args[0]["attendees"] == ["ana@valenin.com", "ben@valenin.com"]
    assert "Valenin" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_an_unresolvable_name_is_surfaced_and_still_creates_the_event(modname):
    con = mock.MagicMock()
    con.resolve.return_value = {"emails": [], "matched": [],
                                "problems": ['Couldn\'t find "markting" in your contacts']}

    sent, cal, _ = drive(modname, cal_intent(invite=["markting"]), contacts_stub=con)

    assert cal.create_event.called
    assert "markting" in sent[-1]


@pytest.mark.parametrize("modname", MODULES)
def test_a_contacts_failure_still_creates_the_event(modname):
    con = mock.MagicMock()
    con.resolve.side_effect = RuntimeError("people api down")

    sent, cal, _ = drive(modname, cal_intent(invite=["Valenin"]), contacts_stub=con)

    assert cal.create_event.called
    assert "Added!" in sent[-1]
    assert "invite" in sent[-1].lower()
