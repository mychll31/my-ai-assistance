import logging

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_FIELDS = "names,emailAddresses,memberships"


def _display_name(person: dict) -> str:
    names = person.get("names") or [{}]
    return names[0].get("displayName") or "(no name)"


def _email(person: dict) -> str | None:
    for e in person.get("emailAddresses") or []:
        if e.get("value"):
            return e["value"]
    return None


def _group_ids(person: dict) -> set[str]:
    ids = set()
    for m in person.get("memberships") or []:
        ref = (m.get("contactGroupMembership") or {}).get("contactGroupResourceName")
        if ref:
            ids.add(ref)
    return ids


class ContactsService:
    def __init__(self, auth_service):
        self._auth = auth_service  # shares CalendarService credentials

    def _svc(self):
        creds = self._auth.creds
        if not creds.valid:
            creds.refresh(Request())
            self._auth._save()
        return build("people", "v1", credentials=creds)

    def _fetch(self):
        svc = self._svc()
        groups = svc.contactGroups().list(pageSize=200).execute().get("contactGroups", [])
        people = svc.people().connections().list(
            resourceName="people/me", personFields=_FIELDS, pageSize=1000,
        ).execute().get("connections", [])
        # System groups like "myContacts" hold the entire address book — never a label.
        labels = {g["name"].lower(): g["resourceName"] for g in groups
                  if g.get("groupType") == "USER_CONTACT_GROUP"}
        return labels, people

    def resolve(self, names: list[str]) -> dict:
        """Turn label and contact names into invitee emails. Never guesses."""
        labels, people = self._fetch()
        emails: list[str] = []
        matched: list[dict] = []
        problems: list[str] = []

        def add(email):
            if email not in emails:
                emails.append(email)

        for raw in names:
            name = (raw or "").strip()
            if not name:
                continue
            if "@" in name:
                problems.append(f'"{name}" is an address, not a contact — not invited')
                continue

            group_ref = labels.get(name.lower())
            if group_ref:
                members = [p for p in people if group_ref in _group_ids(p)]
                found = [_email(p) for p in members if _email(p)]
                missing = [_display_name(p) for p in members if not _email(p)]
                for e in found:
                    add(e)
                if missing:
                    problems.append(f'In "{name}": {", ".join(missing)} — no email address')
                if not found and not missing:
                    problems.append(f'Label "{name}" has no members')
                else:
                    matched.append({"name": name, "kind": "label", "count": len(found)})
                continue

            hits = [p for p in people if name.lower() in _display_name(p).lower()]
            if not hits:
                problems.append(f'Couldn\'t find "{name}" in your contacts')
            elif len(hits) > 1:
                # Picking one would mean emailing the wrong person.
                who = ", ".join(_display_name(p) for p in hits)
                problems.append(f'"{name}" matches {len(hits)} contacts: {who} — nobody invited')
            elif not _email(hits[0]):
                problems.append(f"{_display_name(hits[0])} has no email address")
            else:
                add(_email(hits[0]))
                matched.append({"name": _display_name(hits[0]), "kind": "person", "count": 1})

        return {"emails": emails, "matched": matched, "problems": problems}
