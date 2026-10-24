"""Dan's Google account (kit.google): signing in, Gmail, Calendar, the mail and
calendar packs, the brief parts, reminders, `kit check` and `kit google`."""

import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.checks import Status, check_google
from kit.cli import main
from kit.google import CALENDAR
from kit.google.auth import (
    ClientConfig,
    GoogleAuthError,
    Tokens,
    TokenStore,
    code_from_reply,
    exchange_code,
    scopes_for,
    start_sign_in,
)
from kit.google.calendar import (
    Calendars,
    plant_reminders,
    read_when,
    write_contents,
    zone_for,
)
from kit.google.client import NOT_CONNECTED, RECONNECT, Google, GoogleError
from kit.google.gmail import SOMEONE_ELSES, Gmail, compose, for_model, strip_html
from kit.memory import Memory
from kit.recall import Recall
from kit.settings import Settings
from kit.settings_store import SettingsStore
from kit.tools import ToolCall
from kit.tools.confirm import needs_yes

SYD = timezone(timedelta(hours=10))
NOW = datetime(2026, 10, 23, 9, 0, tzinfo=SYD)


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(mid, sender, subject, text="", html="", attachment="", unread=True):
    parts = []
    if text:
        parts.append({"mimeType": "text/plain", "body": {"data": b64(text)}})
    if html:
        parts.append({"mimeType": "text/html", "body": {"data": b64(html)}})
    if attachment:
        parts.append({"mimeType": "application/pdf", "filename": attachment, "body": {}})
    return {
        "id": mid,
        "threadId": "t" + mid,
        "labelIds": ["INBOX", "UNREAD"] if unread else ["INBOX"],
        "snippet": "Hi Dan, just checking &#39;bout Thursday",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": "dan@example.com"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Thu, 22 Oct 2026 08:15:00 +1000"},
                {"name": "Message-ID", "value": f"<{mid}@mail.example.com>"},
            ],
            "parts": parts,
        },
    }


def _within(event: dict, lo: str, hi: str) -> bool:
    """Google's own rule: the event starts before timeMax and ends after timeMin."""
    start, end = event.get("start") or {}, event.get("end") or {}
    if "status" in event or not lo or not hi:
        return True
    s = start.get("dateTime") or start["date"] + "T00:00:00+10:00"
    e = end.get("dateTime") or end["date"] + "T00:00:00+10:00"
    s, e = datetime.fromisoformat(s), datetime.fromisoformat(e)
    return s < datetime.fromisoformat(hi) and e > datetime.fromisoformat(lo)


class FakeGoogle:
    """Google's token endpoint, Gmail and Calendar, over an httpx MockTransport."""

    def __init__(self, refresh_ok=True):
        self.refresh_ok = refresh_ok
        self.refreshes = 0
        self.posts: list[tuple[str, dict]] = []
        self.patches: list[tuple[str, dict]] = []
        self.messages = {
            "m1": gmail_message(
                "m1", "Sam Smith <sam@example.com>", "Thursday?", text="Does Thursday 2 pm work?"
            ),
            "m2": gmail_message(
                "m2",
                "Council <no-reply@council.example.com>",
                "Bins",
                html="<p>Your bins are <b>late</b>.<br>Sorry.</p><style>p{}</style>",
                attachment="notice.pdf",
                unread=False,
            ),
        }
        self.calendars = [
            {"id": "dan@example.com", "summary": "Dan", "primary": True, "accessRole": "owner"},
            {"id": "work@group", "summary": "Work", "accessRole": "reader", "selected": True},
            {"id": "hidden@group", "summary": "Hidden", "accessRole": "owner", "selected": False},
        ]
        self.events = {
            "dan@example.com": [
                {
                    "id": "e1",
                    "summary": "Dentist",
                    "location": "Richmond Dental",
                    "start": {"dateTime": "2026-10-23T14:00:00+10:00"},
                    "end": {"dateTime": "2026-10-23T15:00:00+10:00"},
                },
                {
                    "id": "e2",
                    "summary": "Camping",
                    "start": {"date": "2026-10-24"},
                    "end": {"date": "2026-10-26"},
                },
                {"id": "gone", "summary": "Cancelled", "status": "cancelled"},
            ],
            "work@group": [
                {
                    "id": "w1",
                    "summary": "Shutdown planning",
                    "start": {"dateTime": "2026-10-23T09:10:00+10:00"},
                    "end": {"dateTime": "2026-10-23T10:00:00+10:00"},
                }
            ],
        }
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            if path == "/revoke":
                return httpx.Response(200)
            if form.get("grant_type") == ["authorization_code"]:
                self.posts.append(("code", {k: v[0] for k, v in form.items()}))
                return httpx.Response(
                    200,
                    json={
                        "access_token": "at1",
                        "refresh_token": "rt1",
                        "expires_in": 3600,
                        "scope": " ".join(scopes_for(True, True)),
                    },
                )
            self.refreshes += 1
            if not self.refresh_ok:
                return httpx.Response(
                    400, json={"error": "invalid_grant", "error_description": "Token revoked"}
                )
            return httpx.Response(
                200, json={"access_token": f"at{self.refreshes + 1}", "expires_in": 3600}
            )
        if request.headers.get("Authorization") != "Bearer " + self.expect_token:
            return httpx.Response(401, json={"error": {"message": "bad token"}})
        if path == "/gmail/v1/users/me/profile":
            return httpx.Response(200, json={"emailAddress": "dan@example.com"})
        if path == "/gmail/v1/users/me/messages":
            q = request.url.params.get("q", "")
            found = [
                m
                for m in self.messages.values()
                if "is:unread" not in q or "UNREAD" in m["labelIds"]
            ]
            if "from:" in q:
                who = q.split("from:")[1].split()[0]
                found = [m for m in found if who in json.dumps(m)]
            self.last_query = q
            return httpx.Response(200, json={"messages": [{"id": m["id"]} for m in found]})
        if path.startswith("/gmail/v1/users/me/messages/") and request.method == "GET":
            mid = path.rsplit("/", 1)[1]
            if mid not in self.messages:
                return httpx.Response(404, json={"error": {"message": "Not Found"}})
            return httpx.Response(200, json=self.messages[mid])
        if path in ("/gmail/v1/users/me/drafts", "/gmail/v1/users/me/messages/send"):
            self.posts.append((path.rsplit("/", 1)[1], json.loads(request.content)))
            return httpx.Response(200, json={"id": "d1" if "drafts" in path else "sent1"})
        if path == "/calendar/v3/users/me/calendarList":
            return httpx.Response(200, json={"items": self.calendars})
        if path == "/calendar/v3/calendars/primary":
            return httpx.Response(200, json={"id": "dan@example.com"})
        if path.startswith("/calendar/v3/calendars/") and path.endswith("/events"):
            cal = path.split("/")[4]
            q = request.url.params.get("q", "").lower()
            lo, hi = request.url.params.get("timeMin", ""), request.url.params.get("timeMax", "")
            items = [
                e
                for e in self.events.get(cal, [])
                if (not q or q in e.get("summary", "").lower()) and _within(e, lo, hi)
            ]
            if request.method == "POST":
                body = json.loads(request.content)
                self.posts.append((cal, body))
                return httpx.Response(200, json={"id": "new1", **body})
            return httpx.Response(200, json={"items": items})
        if path.startswith("/calendar/v3/calendars/") and request.method == "PATCH":
            cal, eid = path.split("/")[4], path.rsplit("/", 1)[1]
            body = json.loads(request.content)
            self.patches.append((cal, eid, body))
            old = next(e for e in self.events[cal] if e["id"] == eid)
            return httpx.Response(200, json={**old, **body})
        return httpx.Response(404, json={"error": {"message": f"no route {path}"}})

    expect_token = "at1"


@pytest.fixture
def fake():
    return FakeGoogle()


def signed_in(paths, fake, fresh=True, **extra) -> TokenStore:
    paths.ensure()
    store = TokenStore(paths.secrets_dir)
    store.client_file.write_text(
        json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}})
    )
    store.save(
        Tokens(
            "rt1",
            "at1" if fresh else "",
            (NOW + timedelta(hours=1)).isoformat() if fresh else "",
            scopes_for(True, True),
            "dan@example.com",
            **extra,
        )
    )
    return store


def google_for(paths, fake, **kw) -> Google:
    return Google(signed_in(paths, fake, **kw), lambda: NOW, fake.http)


# --- signing in ---------------------------------------------------------------


def test_the_sign_in_address_carries_the_client_scopes_and_pkce(tmp_path):
    path = tmp_path / "google_client.json"
    path.write_text(json.dumps({"installed": {"client_id": "cid.apps", "client_secret": "s"}}))
    client = ClientConfig.load(path)
    sign_in = start_sign_in(client, scopes_for(True, False), 8765)
    q = parse_qs(urlparse(sign_in.url).query)
    assert q["client_id"] == ["cid.apps"] and q["redirect_uri"] == ["http://localhost:8765/"]
    assert "gmail.readonly" in q["scope"][0] and "calendar" not in q["scope"][0]
    assert q["code_challenge_method"] == ["S256"] and q["state"] == [sign_in.state]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    path.write_text("{}")
    with pytest.raises(GoogleAuthError, match="no client_id"):
        ClientConfig.load(path)


def test_the_reply_can_be_the_whole_address_or_the_bare_code():
    assert code_from_reply("http://localhost:8765/?state=s1&code=4/abc&scope=x", "s1") == "4/abc"
    assert code_from_reply("  4/abc  ", "s1") == "4/abc"
    with pytest.raises(GoogleAuthError, match="another sign-in"):
        code_from_reply("http://localhost:8765/?state=other&code=4/abc", "s1")
    with pytest.raises(GoogleAuthError, match="Google said no"):
        code_from_reply("http://localhost:8765/?error=access_denied&state=s1", "s1")
    with pytest.raises(GoogleAuthError, match="nothing pasted"):
        code_from_reply("", "s1")


def test_the_code_becomes_tokens_kept_owner_only(paths, fake):
    client = ClientConfig("cid", "sec")
    sign_in = start_sign_in(client, scopes_for(True, True), 8765)
    tokens = asyncio.run(exchange_code(fake.http, client, sign_in, "4/abc", NOW))
    assert tokens.refresh_token == "rt1" and tokens.has("gmail") and tokens.has("calendar")
    sent = fake.posts[0][1]
    assert (
        sent["code_verifier"] == sign_in.verifier and sent["redirect_uri"] == sign_in.redirect_uri
    )
    store = TokenStore(paths.secrets_dir)
    store.save(tokens)
    assert store.load().account == "" and store.load().fresh(NOW)
    if sys.platform != "win32":
        assert oct(os.stat(store.token_file).st_mode & 0o777) == "0o600"
    assert store.forget() and store.load() is None


def test_a_stale_access_token_is_refreshed_and_a_revoked_one_asks_to_reconnect(paths, fake):
    google = google_for(paths, fake, fresh=False)
    fake.expect_token = "at2"
    assert asyncio.run(google.access_token()) == "at2" and fake.refreshes == 1
    assert asyncio.run(google.access_token()) == "at2" and fake.refreshes == 1  # fresh now
    assert google.store.load().access_token == "at2"  # kept for the next start
    gone = FakeGoogle(refresh_ok=False)
    google = Google(signed_in(paths, gone, fresh=False), lambda: NOW, gone.http)
    with pytest.raises(GoogleError, match="needs reconnecting") as e:
        asyncio.run(google.access_token())
    assert e.value.reconnect and not google.connected and google.status()["needs_reconnect"]
    assert google.store.load().needs_reconnect  # Kit says so on every start till it's fixed
    with pytest.raises(GoogleError, match=RECONNECT[:20]):
        asyncio.run(google.get("/gmail/v1/users/me/profile"))


def test_not_signed_in_is_said_plainly(paths, fake):
    paths.ensure()
    google = Google(TokenStore(paths.secrets_dir), lambda: NOW, fake.http)
    assert not google.connected and google.status() == {
        "connected": False, "account": "", "gmail": False, "calendar": False,
    }  # fmt: skip
    with pytest.raises(GoogleError, match=NOT_CONNECTED):
        asyncio.run(google.get("/gmail/v1/users/me/profile"))


# --- Gmail ---------------------------------------------------------------------


def test_search_and_read_mark_the_mail_as_someone_elses_words(paths, fake):
    gmail = Gmail(google_for(paths, fake))
    found = asyncio.run(gmail.search("", 5))
    assert [m.id for m in found] == ["m1", "m2"] and fake.last_query == "in:inbox newer_than:3d"
    assert found[0].line().startswith("[m1] Thu 22 Oct 08:15 from Sam Smith (unread): Thursday?")
    assert "'bout" in found[0].line()  # the snippet's &#39; is unescaped
    unread = asyncio.run(gmail.search("is:unread", 5))
    assert [m.id for m in unread] == ["m1"]
    m = asyncio.run(gmail.read("m1"))
    assert m.text == "Does Thursday 2 pm work?" and m.message_id == "<m1@mail.example.com>"
    shown = for_model(m)
    assert shown.startswith("From: Sam Smith <sam@example.com>\nTo: dan@example.com")
    assert f"\n\n{SOMEONE_ELSES}\nDoes Thursday 2 pm work?" in shown
    council = asyncio.run(gmail.read("m2"))
    assert council.text == "Your bins are late.\nSorry." and council.attachments == ["notice.pdf"]
    assert "Attachments (names only" in for_model(council)
    with pytest.raises(GoogleError, match="Google said no \\(404\\): Not Found"):
        asyncio.run(gmail.read("nope"))


def test_html_is_stripped_and_long_mail_is_cut():
    assert strip_html("<div>a<br>b</div><script>x()</script>&amp;") == "a\nb\n&"
    from kit.google.gmail import BODY_CHARS, Message

    m = Message("x", "t", "a@b", "c@d", "s", "", text="word " * (BODY_CHARS // 2))
    assert for_model(m).endswith("[...cut here]")


def test_a_reply_stays_in_its_conversation_and_sending_posts_the_raw_message(paths, fake):
    gmail = Gmail(google_for(paths, fake))
    orig = asyncio.run(gmail.read("m1"))
    mail = compose("", "", "Thursday works.", orig)
    assert mail["To"] == "" and mail["Subject"] == "Re: Thursday?"
    assert mail["In-Reply-To"] == "<m1@mail.example.com>" == mail["References"]
    mail = compose("sam@example.com", "Re: Thursday?", "Thursday works.", orig)
    assert mail["Subject"] == "Re: Thursday?"
    assert asyncio.run(gmail.draft(mail, orig.thread_id)) == "d1"
    assert asyncio.run(gmail.send(mail, orig.thread_id)) == "sent1"
    (kind, draft), (kind2, sent) = fake.posts
    assert (kind, kind2) == ("drafts", "send") and draft["message"]["threadId"] == "tm1"
    raw = base64.urlsafe_b64decode(sent["raw"] + "==").decode()
    assert "To: sam@example.com" in raw and "Thursday works." in raw and sent["threadId"] == "tm1"


# --- Calendar -------------------------------------------------------------------


def calendars_for(paths, fake, chosen=()):
    google = google_for(paths, fake)
    return Calendars(google, lambda: NOW, lambda: SYD, lambda: list(chosen))


def test_events_come_from_the_calendars_dan_shows_in_order(paths, fake):
    cals = calendars_for(paths, fake)
    events = asyncio.run(cals.refresh())
    assert [c.name for c in cals.calendars] == ["Dan", "Work"]  # Hidden isn't selected
    assert [e.title for e in events] == ["Shutdown planning", "Dentist", "Camping"]
    dentist = events[1]
    assert (
        dentist.line(NOW.date())
        == "[dan@example.com:e1] today 2 pm to 3 pm: Dentist, at Richmond Dental (Dan)"
    )
    assert events[2].when(NOW.date()) == "tomorrow to Sun 25 Oct" and events[2].all_day
    assert [e.title for e in cals.today(NOW)] == ["Shutdown planning", "Dentist"]
    assert [e.title for e in cals.find("dentist")] == ["Dentist"]
    assert cals.find("dan@example.com:e1")[0].id == "e1" and cals.find("x") == []
    only = calendars_for(paths, fake, chosen=["work"])
    asyncio.run(only.refresh())
    assert [c.name for c in only.calendars] == ["Work"]
    found = asyncio.run(cals.events_between(NOW, NOW + timedelta(days=7), "dent"))
    assert [e.title for e in found] == ["Dentist"]


def test_times_the_model_writes_are_read_in_dans_zone():
    t, all_day = read_when("2026-10-24T14:00", SYD)
    assert t == datetime(2026, 10, 24, 14, 0, tzinfo=SYD) and not all_day
    t, all_day = read_when("2026-10-24", SYD)
    assert t.date().isoformat() == "2026-10-24" and all_day
    assert read_when("2026-10-24T04:00:00Z", SYD)[0].hour == 14
    with pytest.raises(ValueError, match="can't read the time"):
        read_when("Thursday arvo", SYD)
    assert zone_for("Australia/Sydney").utcoffset(datetime(2026, 7, 1)) == timedelta(hours=10)
    assert zone_for("Mars/Olympus") is not None  # falls back to this machine's


def test_adding_and_moving_go_to_the_right_calendar(paths, fake):
    cals = calendars_for(paths, fake)
    asyncio.run(cals.refresh())
    ev = asyncio.run(
        cals.add(
            "Haircut",
            datetime(2026, 10, 27, 10, 0, tzinfo=SYD),
            None,
            False,
            "Richmond",
            tz_name="Australia/Sydney",
        )
    )
    cal, body = fake.posts[-1]
    assert (
        cal == "dan@example.com" and body["summary"] == "Haircut" and body["location"] == "Richmond"
    )
    assert body["start"] == {
        "dateTime": "2026-10-27T10:00:00+10:00",
        "timeZone": "Australia/Sydney",
    }
    assert body["end"]["dateTime"].startswith("2026-10-27T11:00")
    assert ev.id == "new1" and any(e.id == "new1" for e in cals.events)
    day = asyncio.run(cals.add("Birthday", datetime(2026, 11, 2, tzinfo=SYD), None, True))
    assert fake.posts[-1][1]["start"] == {"date": "2026-11-02"} and day.all_day
    with pytest.raises(ValueError, match="read only"):
        asyncio.run(cals.add("X", NOW, None, False, calendar="Work"))
    with pytest.raises(ValueError, match="no calendar called"):
        asyncio.run(cals.add("X", NOW, None, False, calendar="Nope"))
    dentist = cals.find("dentist")[0]
    moved = asyncio.run(cals.move(dentist, datetime(2026, 10, 23, 16, 0, tzinfo=SYD), None))
    assert fake.patches == [
        (
            "dan@example.com",
            "e1",
            {
                "start": {"dateTime": "2026-10-23T16:00:00+10:00"},
                "end": {"dateTime": "2026-10-23T17:00:00+10:00"},
            },
        )
    ]
    assert moved.start.hour == 16 and cals.find("dentist")[0].start.hour == 16


def test_coming_events_go_into_memory_and_one_about_to_start_becomes_a_want(paths, fake):
    memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-23T09:00:00"))
    from kit.notebook import Notebook

    cals = calendars_for(paths, fake)
    events = asyncio.run(cals.refresh())
    assert write_contents(memory.index, events) == 3
    items = memory.index.items(CALENDAR, limit=10)
    assert {i.title for i in items} == {"Dentist", "Camping", "Shutdown planning"}
    dentist = next(i for i in items if i.title == "Dentist")
    assert dentist.text == "Dentist, Fri 23 Oct 2 pm to 3 pm at Richmond Dental (Dan calendar)."
    assert dentist.meta["day"] == "2026-10-23" and dentist.ref == "dan@example.com:e1"
    notebook = Notebook(memory)
    now = memory.clock()
    assert plant_reminders(notebook, events, now, 15, "Dan") == 1  # the 9:10 one, not the 2 pm
    assert plant_reminders(notebook, events, now, 15, "Dan") == 0  # once
    want = notebook.open_wants()[0]
    assert want.text == "Remind Dan: Shutdown planning starts at 9:10 am, in about 10 minutes."
    assert want.meta["event"] == "work@group:w1" and want.meta["until"].startswith(
        "2026-10-23T09:10"
    )
    memory.clock.now = datetime.fromisoformat("2026-10-23T09:11:00")
    assert notebook.open_wants() == []  # started: not worth saying any more
    assert plant_reminders(notebook, events, now, 0, "Dan") == 0
    memory.close()


# --- in the brain ---------------------------------------------------------------


def make_brain(paths, fake, *outputs, claude=None, **google_settings):
    store = SettingsStore(paths)
    store.update(
        {
            "google": {"enabled": True, **google_settings},
            "persona": {"timezone": "Australia/Brisbane"},
            "routing": {"mode": "cloud-only"},
            "memory": {"min_similarity": 0.3},
        },
        "test",
    )
    memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-23T09:00:00"))
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, model, make_cloud(memory, claude), recall)
    brain.google_tz = lambda: SYD  # the same zone on every machine, zone database or not
    brain.use_google(google_for(paths, fake))
    return brain, memory, claude


def run(brain, name, **args):
    return asyncio.run(brain.tools.run(ToolCall("1", name, args)))


def test_the_mail_pack_searches_reads_and_drafts(paths, fake):
    brain, memory, _ = make_brain(paths, fake)
    assert {"mail", "calendar"} <= set(brain.tools.packs)
    out = run(brain, "mail_search", query="from:sam")
    assert out.ok and "[m1]" in out.text and "senders' own words" in out.text
    assert run(brain, "mail_search", query="from:nobody").text == "No mail matches from:nobody."
    out = run(brain, "mail_read", id="m1")
    assert SOMEONE_ELSES in out.text and out.step == "read the email from Sam Smith"
    out = run(brain, "mail_draft", reply_to="m1", body="Thursday works.")
    assert out.ok and out.text.startswith("Done: drafted an email to Sam Smith <sam@example.com>")
    assert "Drafts for Dan" in out.text and fake.posts[-1][0] == "drafts"
    assert run(brain, "mail_draft", body="hi").text == "Not drafted: no one to send it to."
    memory.close()


def test_sending_always_asks_with_the_message_shown(paths, fake):
    brain, memory, _ = make_brain(paths, fake)
    pack = brain.tools.packs["mail"]
    send = next(t for t in pack.tools if t.name == "mail_send")
    args = {"to": "sam@example.com", "subject": "Thursday", "body": "Works for me."}
    assert needs_yes(send, pack, brain.settings(), args)
    assert send.asking(ToolCall("1", "mail_send", args)) == "send this email to sam@example.com"
    assert send.preview(args) == "To: sam@example.com\nSubject: Thursday\n\nWorks for me."
    assert send.preview({"reply_to": "m1", "body": "Ok"}).startswith(
        "To: the sender (a reply)\nSubject: Re: the original"
    )
    assert "mail_send" in {t.name for t in brain.tools.offered(["mail"])}
    out = run(brain, "mail_send", reply_to="m1", body="Works for me.")
    assert out.ok and out.text.startswith("Done: sent the email to Sam Smith")
    memory.close()
    brain, memory, _ = make_brain(paths, fake, send=False)
    assert "mail_send" not in {t.name for t in brain.tools.offered(["mail"])}
    assert "mail_draft" in {t.name for t in brain.tools.offered(["mail"])}
    memory.close()


def test_sending_waits_for_a_yes_in_the_chat(paths, fake):
    claude = FakeAnthropic(
        answer=["", reply("Send Sam 'Thursday works'?"), reply("Sent.")],
        tool_calls=[[("mail_send", {"reply_to": "m1", "body": "Thursday works."})]],
    )
    brain, memory, _ = make_brain(paths, fake, claude=claude)
    collect(brain.chat("reply to sam saying thursday works"))
    assert "mail" in brain.loaded_packs
    assert brain.pending_tool is not None and not any(k == "send" for k, _ in fake.posts)
    assert "Thursday works." in brain.pending_tool.preview
    collect(brain.chat("yes"))
    assert [k for k, _ in fake.posts] == ["send"]
    memory.close()


def test_the_calendar_pack_lists_adds_and_moves(paths, fake):
    brain, memory, _ = make_brain(paths, fake)
    out = run(brain, "calendar_events", days=1)
    assert out.ok and "today 2 pm to 3 pm: Dentist" in out.text and "(Dan, Work)" in out.text
    assert "Camping" not in out.text
    out = run(brain, "calendar_events", query="dentist", days=30)
    assert "Dentist" in out.text and "Shutdown" not in out.text
    assert run(brain, "calendar_events", query="zzz").text.startswith("Nothing on matching 'zzz'")
    assert run(brain, "calendar_events", **{"from": "yesterday"}).text.startswith(
        "can't read the time"
    )
    pack = brain.tools.packs["calendar"]
    add = next(t for t in pack.tools if t.name == "calendar_add")
    args = {"title": "Haircut", "start": "2026-10-27T10:00", "where": "Richmond"}
    assert needs_yes(add, pack, brain.settings(), args)
    assert add.preview(args) == "Haircut: Tue 27 Oct 10:00 AM, at Richmond"
    out = run(brain, "calendar_add", **args)
    assert out.text == "Done: added 'Haircut' to the Dan calendar, Tue 27 Oct 10 am to 11 am."
    assert fake.posts[-1][1]["start"]["timeZone"] == "Australia/Brisbane"
    out = run(brain, "calendar_move", event="dentist", start="2026-10-23T16:00")
    assert out.text == "Done: moved 'Dentist' to today 4 pm to 5 pm."
    assert run(brain, "calendar_move", event="zzz", start="2026-10-23T16:00").text.startswith(
        "No coming event"
    )
    memory.close()
    brain, memory, _ = make_brain(paths, fake, calendar_write=False)
    offered = {t.name for t in brain.tools.offered(["calendar"])}
    assert offered == {"calendar_events"}
    memory.close()


def test_the_calendar_tick_keeps_memory_and_reminders(paths, fake):
    brain, memory, _ = make_brain(paths, fake)
    assert asyncio.run(brain.calendar_tick()) == 3
    assert memory.index.count(CALENDAR) == 3
    assert brain.notebook.open_wants()[0].text.startswith("Remind Dan: Shutdown planning")
    calls = fake.refreshes
    assert asyncio.run(brain.calendar_tick()) == 3 and fake.refreshes == calls  # not yet due again
    memory.close()


def test_the_brief_has_the_calendar_and_new_mail(paths, fake):
    brain, memory, _ = make_brain(paths, fake)
    sources = brain.brief.sources
    cal = asyncio.run(sources["calendar"](memory.clock()))
    assert (
        cal
        == "On the calendar today: Shutdown planning (9:10 am), Dentist (2 pm at Richmond Dental)."
    )
    mail = asyncio.run(sources["mail"](memory.clock()))
    assert mail == "New mail, unread: Sam Smith about Thursday?."
    assert "category:primary" in fake.last_query
    memory.close()


def test_a_private_google_keeps_mail_from_the_cloud(paths, fake):
    brain, memory, _ = make_brain(paths, fake, private=True)
    assert run(brain, "mail_read", id="m1").private
    assert run(brain, "calendar_events", days=1).private
    memory.close()


def test_without_a_sign_in_the_tools_say_so(paths, fake):
    brain, memory, _ = make_brain(paths, fake)
    brain.google.store.forget()
    brain.google.reload()
    out = run(brain, "mail_search")
    assert not out.ok and out.text == NOT_CONNECTED
    assert asyncio.run(brain.calendar_tick()) == 0
    memory.close()


# --- kit check and kit google ------------------------------------------------------


def test_check_google_says_where_things_stand(paths, fake):
    paths.ensure()
    s = Settings()
    assert check_google(s, paths).status is Status.SKIP
    s = Settings.model_validate({"google": {"enabled": True}})
    assert "no google_client.json" in check_google(s, paths).detail
    store = TokenStore(paths.secrets_dir)
    store.client_file.write_text(json.dumps({"installed": {"client_id": "cid"}}))
    assert "kit google connect" in check_google(s, paths).detail
    signed_in(paths, fake)
    fake.expect_token = "at2"  # the check runs on the real clock, so it refreshes first
    r = check_google(s, paths, fake.http)
    assert (
        r.status is Status.PASS
        and r.detail == "signed in as dan@example.com: mail, calendar (Dan, Work)"
    )
    s = Settings.model_validate(
        {"google": {"enabled": True, "send": False, "calendar_write": False}}
    )
    assert check_google(s, paths, fake.http).detail.endswith("; read only")
    gone = FakeGoogle(refresh_ok=False)
    signed_in(paths, gone, fresh=False)
    r = check_google(s, paths, gone.http)
    assert r.status is Status.FAIL and "needs reconnecting" in r.detail


def test_kit_google_connect_and_disconnect(paths, fake, capsys, monkeypatch):
    from kit import cli

    paths.ensure()
    store = TokenStore(paths.secrets_dir)
    store.client_file.write_text(
        json.dumps({"installed": {"client_id": "cid", "client_secret": "s"}})
    )
    SettingsStore(paths).update({"google": {"enabled": True}}, "test")
    asked = []

    def ask(prompt):
        asked.append(prompt)
        url = capsys.readouterr().out.split("\n")[2]
        state = parse_qs(urlparse(url).query)["state"][0]
        return f"http://localhost:8799/?state={state}&code=4/abc&scope=x"

    args = argparse.Namespace(action="connect", port=8799)
    assert cli.cmd_google(paths, args, fake.http, ask) == 0
    assert "signed in as dan@example.com: gmail, calendar" in capsys.readouterr().out
    tokens = store.load()
    assert tokens.refresh_token == "rt1" and tokens.account == "dan@example.com"
    args = argparse.Namespace(action="status")
    assert cli.cmd_google(paths, args, fake.http) == 0
    assert "signed in as dan@example.com" in capsys.readouterr().out
    args = argparse.Namespace(action="disconnect")
    assert cli.cmd_google(paths, args, fake.http) == 0
    assert "revoked at Google" in capsys.readouterr().out and store.load() is None
    assert main(["google", "status"]) == 1
    assert "not signed in" in capsys.readouterr().out
