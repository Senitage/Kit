"""The desk app's windows, run without a screen. Needs the desk extra."""

import gc
import os

import pytest

pytest.importorskip("PySide6.QtWidgets", reason="desk extra (PySide6) not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from kit.desk import app as desk_app  # noqa: E402
from kit.desk.chat import ChatWindow, place_beside  # noqa: E402
from kit.desk.config import DeskConfig, save_token  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def tidy_qt():
    """Free each test's windows when it ends. Left to Python's garbage collector, a
    finished test's Qt objects can be deleted in the middle of a later test's event
    loop, which crashes Qt on Windows."""
    yield
    gc.collect()
    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def desk_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KIT_DESK_DIR", str(tmp_path))
    return tmp_path


def reply_event(text, detail="", source="local", **extra):
    return {
        "type": "reply",
        "source": source,
        "reply": {
            "emotion": "happy",
            "segments": [{"say": text, "gesture": "nod"}],
            "action": {"kind": "none"},
            "detail": detail,
        },
        **extra,
    }


def test_chat_shows_streamed_words_then_the_reply(qapp):
    chat = ChatWindow()
    acted, states = [], []
    chat.replied.connect(acted.append)
    chat.state.connect(states.append)
    chat.on_event(1, {"type": "say", "text": "Pulling "})
    chat.on_event(1, {"type": "say", "text": "that up."})
    assert "Pulling that up." in chat.text() and states[-1] == "speaking"
    chat.on_event(1, reply_event("Pulling that up.", detail="pump.py line 40"))
    assert chat.text().count("Pulling that up.") == 1
    assert "pump.py line 40" in chat.text()
    assert acted[0]["emotion"] == "happy"
    chat.on_event(2, {"type": "looked_at_pc"})
    assert states[-1] == "looking at your PC"
    chat.on_event(2, {"type": "remembered", "decision": "new", "fact": "Dan likes tea."})
    chat.on_event(2, {"type": "thing_suggested", "thing": {"line": "Rex (pet)"}})
    chat.on_event(
        2,
        reply_event(
            "Sonnet says hi.", source="cloud", label="Claude", model="sonnet", cost_usd=0.01
        ),
    )
    text = chat.text()
    assert "Remembered: Dan likes tea." in text
    assert "Add to the register? Rex (pet) (yes or no)" in text
    # Who answered and the price wait for a click on the bubble.
    assert "sonnet" not in text and "$0.010" not in text
    assert ("Answered by", "Claude") in chat.lines[-1].meta
    assert ("Cost", "$0.010") in chat.lines[-1].meta


def test_bubbles_are_coloured_by_who_answered(qapp):
    chat = ChatWindow()
    chat.on_event(1, reply_event("Local hi."))
    chat.on_event(2, reply_event("Haiku hi.", source="cloud", role="chat", model="haiku"))
    chat.on_event(3, reply_event("Sonnet.", source="cloud", role="work", model="sonnet"))
    chat.on_event(4, reply_event("Opus.", source="cloud", role="expert", model="opus"))
    assert [line.tier for line in chat.lines] == ["chat", "chat", "work", "expert"]
    p = chat.palette
    styles = [row.bubble.styleSheet() for row in chat.rows]
    assert p.bubble in styles[0] and p.bubble in styles[1]
    assert p.work in styles[2] and p.expert in styles[3]


def test_a_click_on_a_reply_pops_out_its_details(qapp):
    chat = ChatWindow()
    chat.show()
    chat.on_event(
        1,
        reply_event(
            "Sorted.",
            source="cloud",
            role="work",
            label="Sonnet",
            model="claude-sonnet",
            cost_usd=0.0123,
            searches=2,
        ),
    )
    row = chat.rows[-1]
    row.bubble.clicked.emit()
    shown = [w.text() for w in chat._details.findChildren(QLabel)]
    assert chat._details.isVisible()
    assert {"Sonnet", "claude-sonnet", "Work", "$0.012", "2"} <= set(shown)
    chat._details.hide()
    chat.close()


def test_old_replies_keep_their_colour_and_details(qapp):
    chat = ChatWindow()
    chat._show_history(
        [
            {"role": "user", "text": "Fix it"},
            {
                "role": "kit",
                "text": "Fixed.",
                "source": "cloud",
                "at": "2026-10-08T09:30:00",
                "meta": {"role": "expert", "label": "Opus", "model": "opus", "cost_usd": 0.2},
            },
            {"role": "kit", "text": "Hi.", "source": "local"},
        ]
    )
    assert [line.tier for line in chat.lines] == ["chat", "expert", "chat"]
    assert ("Answered by", "Opus") in chat.lines[1].meta
    assert ("Time", "Thu 08 Oct, 09:30") in chat.lines[1].meta
    assert ("Answered by", "Kit's local model") in chat.lines[2].meta


def test_details_sit_beside_the_chat_on_the_side_with_room():
    window = QRect(100, 100, 400, 600)
    assert place_beside(window, QSize(200, 150), 300) == QPoint(window.right() + 8, 300)


def test_chat_without_a_brain_says_to_set_it_up(qapp):
    chat = ChatWindow()
    states = []
    chat.state.connect(states.append)
    chat.send("hello")
    assert "open Settings" in chat.text() and states[-1] == "idle"


def test_history_is_shown_before_new_lines(qapp):
    chat = ChatWindow()
    chat.on_event(1, reply_event("New one."))
    chat._show_history(
        [
            {"role": "user", "text": "Old question"},
            {"role": "kit", "text": "Old answer", "source": "cloud", "reply": {"detail": "x"}},
        ]
    )
    text = chat.text()
    assert text.index("Old question") < text.index("Old answer") < text.index("New one.")


def test_face_icon_and_click_versus_drag(qapp):
    assert not desk_app.face_icon().isNull()
    assert not desk_app.face_icon(offline=True).isNull()
    face = desk_app.HelperFace(150)
    clicks, moves = [], []
    face.clicked.connect(lambda: clicks.append(1))
    face.moved.connect(moves.append)

    def mouse(kind, x, y):
        pos = QPointF(x, y)
        return QMouseEvent(
            kind,
            pos,
            pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    face.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, 50, 50))
    face.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, 52, 51))
    assert clicks == [1] and moves == []
    face.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, 50, 50))
    face.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, 150, 90))
    face.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, 150, 90))
    assert clicks == [1] and len(moves) == 1


def test_settings_dialog_reads_back_what_was_typed(qapp, desk_dir):
    dialog = desk_app.SettingsDialog(DeskConfig(), "", first_run=True)
    dialog.url.setText("http://192.168.1.20:8600/")
    dialog.token.setText(" tok ")
    dialog.watch.setChecked(False)
    dialog.hidden_words.setPlainText("bank,\nsalary , ")
    config, token, _ = dialog.values()
    assert config.brain_url == "http://192.168.1.20:8600" and token == "tok"
    assert not config.watch and config.hidden_words == ["bank", "salary"]


def test_app_starts_into_the_tray_and_quits(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)  # nothing listens there
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    try:
        assert desk.face.isVisible() and desk.client is not None
        desk.show_chat()
        assert desk.chat.isVisible()
        desk._show_online(False, "can't reach")
        assert desk.face.face.state == "offline"
        desk._show_online(True, "online")
        desk._chat_state("thinking")
        assert desk.face.face.state == "thinking"
        desk.set_watching(False)
        assert DeskConfig.load(desk_dir).watch is False
        desk._act_out(reply_event("Hi")["reply"])
    finally:
        desk.quit()
        desk.chat.close()
        desk.face.close()


def test_glow_sleeps_and_wakes_when_the_brain_says_and_glances_by_himself(qapp):
    from kit.desk.alive import Alive

    face = desk_app.HelperFace(150)
    face.move(400, 300)
    face.show()
    looked = []
    alive = Alive(face, lambda: looked.append(1) or (0, 0, 800, 600), lambda: False)
    alive.fall_asleep()
    assert alive.asleep and alive._awake_pos == face.pos()
    alive.step()
    assert not looked  # asleep: no glancing
    alive.wake_up()
    assert not alive.asleep and face.face.state == "idle"
    alive._next_glance = 0
    alive.step()
    assert looked
    alive.timer.stop()
    face.close()


def test_a_pipe_up_shows_in_the_chat_and_on_the_face(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    acted = []
    desk.performer.perform = acted.append
    try:
        desk._on_life({"type": "fidget", "gesture": "yawn"})
        desk._on_life({"type": "state", "state": "asleep"})
        assert desk.alive.asleep
        desk._on_life(
            {"type": "pipe_up", "reply": reply_event("Still on pumps.py, mate?")["reply"]}
        )
        import time as _t

        end = _t.time() + 1.5
        while _t.time() < end:
            qapp.processEvents()
        assert "Still on pumps.py, mate?" in desk.chat.text()
        assert acted and acted[0]["segments"][0]["say"] == "Still on pumps.py, mate?"
    finally:
        desk.quit()
        desk.chat.close()
        desk.face.close()


def test_new_chat_clears_the_window(qapp):
    class Client:
        started = 0

        def new_chat(self):
            self.started += 1

    client = Client()
    chat = ChatWindow(client)
    chat.on_event(1, reply_event("Old one."))
    chat.new_chat()
    assert client.started == 1 and "Old one." not in chat.text()


def test_reopening_the_chat_shows_the_brains_current_conversation(qapp):
    chat = ChatWindow()
    chat._show_history([{"role": "user", "text": "Old question"}])
    chat._replace = True  # a later open: the brain's conversation is the truth
    chat._show_history([])
    assert "Old question" not in chat.text()


def pump(qapp, seconds=0.4):
    import time as _t

    end = _t.time() + seconds
    while _t.time() < end:
        qapp.processEvents()


def test_kits_markdown_shows_formatted_with_links_in_the_theme_colour(qapp):
    from kit.desk import theme

    chat = ChatWindow(palette=theme.palette("dark", "#14a39a"))
    chat.on_event(1, reply_event("**Bold** and a [link](http://mettools.lan)"))
    bubble = chat.rows[-1].bubble
    html = bubble.body.text()
    assert "font-weight" in html and "http://mettools.lan" in html
    assert "#0000ff" not in html.lower()  # Qt's default blue is replaced
    chat.send("**not markdown**")
    you = next(r.bubble for r in chat.rows if r.line.role == "you")
    assert you.body.textFormat() == Qt.TextFormat.PlainText


def test_the_chat_stays_at_the_bottom_unless_dan_scrolls_up(qapp):
    chat = ChatWindow()
    chat.resize(420, 400)
    chat.show()
    for i in range(30):
        chat.on_event(i, reply_event(f"Line {i} " + "words " * 20))
    pump(qapp)
    bar = chat.scroll.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    bar.setValue(0)  # Dan scrolls up to read
    chat.on_event(99, reply_event("A new one " + "words " * 20))
    pump(qapp)
    assert bar.value() == 0 and chat.jump.isVisible()
    chat.scroll_to_end()
    chat.on_event(100, reply_event("And another " + "words " * 20))
    pump(qapp)
    assert bar.value() == bar.maximum() and not chat.jump.isVisible()
    chat.close()


def test_the_typing_dots_show_until_kit_starts_talking(qapp):
    chat = ChatWindow()
    chat._in_flight = 1
    chat._set_state("thinking")
    assert not chat.typing_row.isHidden()
    chat.on_event(1, {"type": "say", "text": "Hi"})
    assert chat.typing_row.isHidden()


class FakeBrain:
    def __init__(self):
        from kit.settings import Settings

        self.saved = []
        self.store = Settings().model_dump(mode="json")
        self.fact_list = [
            {"id": 1, "text": "Tax is in Finance/Tax", "kind": "place", "pinned": False}
        ]
        self.edits = []

    def settings_schema(self):
        from kit.settings import Settings

        return Settings.model_json_schema()

    def settings(self):
        return {"settings": self.store, "problem": None}

    def save_settings(self, patch):
        self.saved.append(patch)
        return {"settings": self.store, "problem": None}

    def facts(self):
        return self.fact_list

    def remember(self, text, pinned=False):
        self.fact_list = [
            {"id": 2, "text": text, "kind": "other", "pinned": False},
            *self.fact_list,
        ]
        return {"decision": "new"}

    def edit_fact(self, fact_id, **changes):
        self.edits.append((fact_id, changes))

    def search(self, q, k=15):
        return {"hits": [{"source": "facts", "title": "", "text": "Tax is in Finance/Tax"}]}

    def face_presets(self):
        return {
            "current": "retro",
            "presets": [{"id": "retro", "name": "Retro"}, {"id": "kit3d", "name": "Kit 3D"}],
        }


@pytest.fixture
def sync_window(monkeypatch):
    from kit.desk import window

    monkeypatch.setattr(window, "SYNC", True)
    return window


def make_window(window, brain, tmp_path, config=None):
    return window.KitWindow(
        config or DeskConfig(), "tok", "", lambda: brain, lambda: "http://kit:8600", tmp_path
    )


def test_kits_settings_page_round_trips_the_brains_settings(qapp, sync_window, tmp_path):
    brain = FakeBrain()
    win = make_window(sync_window, brain, tmp_path)
    win.show_page("Kit's settings")
    page = win.brain_settings
    assert page.fields
    page.save()
    patch = brain.saved[-1]
    assert patch["brain"]["history_messages"] == brain.store["brain"]["history_messages"]
    assert patch["life"]["cheek"] == pytest.approx(brain.store["life"]["cheek"])
    win.close()


def test_kits_settings_fold_away_and_search(qapp, sync_window, tmp_path):
    brain = FakeBrain()
    win = make_window(sync_window, brain, tmp_path)
    win.show()
    win.show_page("Kit's settings")
    page = win.brain_settings
    assert page.groups and not any(box.body.isVisibleTo(page) for box in page.groups)
    brain_box = next(box for box in page.groups if box.title == "Brain")
    brain_box.head.click()  # Dan opens one
    assert brain_box.body.isVisibleTo(page)
    page.find.setText("history messages")
    shown = [box for box in page.groups if box.isVisibleTo(page)]
    assert shown == [brain_box] and brain_box.body.isVisibleTo(page)
    page.find.setText("no such setting anywhere")
    assert page.nothing.isVisibleTo(page) and not any(b.isVisibleTo(page) for b in page.groups)
    page.find.clear()  # back as Dan left them: only Brain open
    assert all(box.isVisibleTo(page) for box in page.groups)
    assert [box.title for box in page.groups if box.body.isVisibleTo(page)] == ["Brain"]
    page.save()  # a reload keeps it open
    assert [box.title for box in page.groups if box.body.isVisibleTo(page)] == ["Brain"]
    win.close()


def test_look_page_picks_his_character_and_fits_its_style(qapp, sync_window, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_window.face3d, "sync", lambda *args: None)  # no web pages here
    brain = FakeBrain()
    win = make_window(sync_window, brain, tmp_path)
    changed = []
    win.character_changed.connect(lambda: changed.append(True))
    win.show_page("Look")
    look = win.look
    assert [look.character.itemText(i) for i in range(look.character.count())] == [
        "Retro",
        "Kit 3D",
    ]
    look.character.activated.emit(1)
    assert brain.saved[-1] == {"face": {"character": "kit3d"}} and changed
    assert look.eyes.isVisibleTo(look)
    win.use_look("http://kit:8600", {"style": "model"})  # 3D: no eye colours to pick
    assert not look.eyes.isVisibleTo(look) and "3D" in look.style_note.text()
    assert win.mood.gem.y() > 0  # the mood gem comes down onto the 3D head
    win.use_look("http://kit:8600", {"style": "glow"})
    assert look.eyes.isVisibleTo(look) and win.mood.gem.y() == 0
    win.close()


def test_mood_and_look_show_his_3d_face_only_while_the_window_is_open(
    qapp, sync_window, tmp_path, monkeypatch
):
    seen = []

    def sync(widget, url, look, current):
        seen.append((widget, url))
        return "3d" if url else None

    monkeypatch.setattr(sync_window.face3d, "sync", sync)
    win = make_window(sync_window, FakeBrain(), tmp_path)
    win.use_look("http://kit:8600", {"style": "model"})
    assert [url for _, url in seen] == [None, None]  # closed: no web pages
    win.show_page("Mood")
    assert {w for w, url in seen[-2:] if url} == {win.mood.face, win.look.preview}
    assert win._faces3d == ["3d", "3d"]
    win.hide()
    assert [url for _, url in seen[-2:]] == [None, None]
    win.close()


def test_settings_controls_read_back_what_they_show(qapp, sync_window):
    w = sync_window
    for prop, value in [
        ({"type": "string"}, "qwen3:8b"),
        ({"type": "integer", "minimum": 2}, 20),
        ({"type": "boolean"}, True),
        ({"enum": ["a", "b"]}, "b"),
        ({"type": "array", "items": {"type": "string"}}, ["x", "y"]),
        ({"type": "object", "additionalProperties": {"type": "string"}}, {"tax": "Finance/Tax"}),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, None),
        ({"type": "object"}, {"nested": [1, 2]}),
    ]:
        kind = w.kind_of(prop)
        assert w.read_control(kind, w.make_control(kind, prop, value)) == value, kind


def test_memory_page_lists_teaches_and_pins(qapp, sync_window, tmp_path):
    brain = FakeBrain()
    win = make_window(sync_window, brain, tmp_path)
    page = win.memory
    win.show_page("Memory")
    assert page.facts.count() == 1
    page.teach.setText("The Hilux is in Documents/Cars")
    page.remember()
    assert page.facts.count() == 2 and "Remembered" in page.note.text()
    page.facts.setCurrentRow(1)
    page.toggle_pin()
    assert brain.edits == [(1, {"pinned": True})]
    page.query.setText("tax")
    page.search()
    assert "Finance/Tax" in page.results.item(0).text()
    win.close()


def test_look_changes_show_at_once_and_only_touch_the_look(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    try:
        desk.open_window("Look")
        look = desk.window.look
        look.eyes.pick("#ffc66b")
        look.size.setValue(200)
        assert desk.face.eye.name() == "#ffc66b" and round(desk.face.face_rect().width()) == 200
        desk.window.pc.form.url.setText("http://elsewhere:8600")  # typed, not saved
        look.theme.setCurrentIndex(look.theme.findData("light"))
        saved = DeskConfig.load(desk_dir)
        assert saved.eye_colour == "#ffc66b" and saved.theme == "light"
        assert saved.brain_url == "http://127.0.0.1:9"
        assert not desk.chat.palette.dark
    finally:
        desk.quit()
        desk.window.close()
        desk.chat.close()
        desk.face.close()


class FakeUpdater:
    def __init__(self, found):
        self.found = found

    def newer(self):
        return self.found

    def download(self, release, folder, progress=None):
        path = folder / release.asset
        path.write_bytes(b"MZ")
        return path

    def close(self):
        pass


def found_release(has_this_build=True):
    from kit.desk.update import Release

    return Release(
        "0.1.0.99", "desk-v0.1.0.99", "New chat look", "", "", "K.exe", "u", 2, "", has_this_build
    )


def updates_window(window, found, tmp_path):
    updater = FakeUpdater(found)
    return window.KitWindow(
        DeskConfig(), "", "", lambda: None, lambda: "", tmp_path, updater=lambda c, t: updater
    )


def test_updates_page_offers_a_newer_version(qapp, sync_window, tmp_path):
    win = updates_window(sync_window, found_release(), tmp_path)
    installs = []
    win.updates.install.connect(installs.append)
    win.show_page("Updates")
    win.updates.check()
    assert "0.1.0.99" in win.updates.status.text() and not win.updates.install_button.isHidden()
    win.updates.download()
    assert installs and installs[0].name == "K.exe"
    win.close()


def test_updates_page_says_a_release_lacks_a_test_builds_changes(qapp, sync_window, tmp_path):
    win = updates_window(sync_window, found_release(has_this_build=False), tmp_path)
    installs = []
    win.updates.install.connect(installs.append)
    win.show_page("Updates")
    win.updates.check()
    assert "without this test build's changes" in win.updates.status.text()
    assert win.updates.install_button.text() == "Install it anyway"
    win.updates.download()  # Dan's choice: back to main's release
    assert installs and installs[0].name == "K.exe"
    win.close()


def test_the_daily_check_only_offers_a_release_with_a_test_builds_changes(
    qapp, desk_dir, sync_window, monkeypatch
):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    told = []
    monkeypatch.setattr(desk.tray, "showMessage", lambda *args: told.append(args))
    try:
        held = FakeUpdater(found_release(has_this_build=False))
        monkeypatch.setattr(desk_app, "Updater", lambda repo, token: held)
        desk.check_for_update()
        assert desk.window is None and not told  # Kit keeps quiet: it'd lose the test
        ready = FakeUpdater(found_release())
        monkeypatch.setattr(desk_app, "Updater", lambda repo, token: ready)
        desk.check_for_update()
        assert desk.window.isVisible() and "0.1.0.99" in told[0][1]
    finally:
        desk.quit()
        if desk.window is not None:
            desk.window.close()
        desk.chat.close()
        desk.face.close()


def test_a_new_topic_shows_as_a_note(qapp):
    chat = ChatWindow()
    chat.on_event(1, {"type": "new_topic"})
    assert chat.lines[-1].role == "note" and "started fresh" in chat.text()


def test_a_replys_detail_reads_as_part_of_the_same_message(qapp):
    chat = ChatWindow()
    chat.on_event(1, reply_event("Pump's sized.", detail="450 m3/h @ 32 m"))
    bubble = chat.rows[-1].bubble
    assert bubble.text == "Pump's sized.\n\n450 m3/h @ 32 m"
    assert not hasattr(bubble, "detail")  # no separate grey box


def test_messages_and_the_conversation_copy_as_plain_text(qapp):
    from PySide6.QtGui import QGuiApplication

    chat = ChatWindow()
    chat.send("How big a pump?")  # no brain: an error note follows
    chat.on_event(2, reply_event("An 8/6 AH.", detail="1,050 rpm"))
    chat.rows[-1].copy.click()
    assert QGuiApplication.clipboard().text() == "An 8/6 AH.\n\n1,050 rpm"
    chat.copy_conversation()
    pasted = QGuiApplication.clipboard().text()
    assert pasted.startswith("Me: How big a pump?\n\n[Kit isn't set up yet")
    assert pasted.endswith("Kit: An 8/6 AH.\n\n1,050 rpm")
    assert chat.status.text() == "Copied the conversation"


def test_his_face_listens_while_dan_types_to_him(qapp):
    chat = ChatWindow()
    states = []
    chat.state.connect(states.append)
    chat.input.setPlainText("Hey Kit, guess what")
    assert states[-1] == "listening"
    chat.input.setPlainText("Hey Kit, guess what happened")
    assert states.count("listening") == 1  # once, not every key
    chat.input.clear()
    assert states[-1] == "idle"
    assert desk_app.FACE_STATES["listening"] == "listening"


def test_a_reaction_plays_even_mid_conversation(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    played = []
    monkeypatch.setattr(desk.face.face, "play", lambda gesture, now: played.append(gesture))
    try:
        desk.chat._in_flight = 1  # answering something
        desk._on_life({"type": "fidget", "gesture": "yawn"})
        desk._on_life({"type": "react", "gesture": "wave"})
        assert played == ["wave"]  # a fidget waits; a reaction doesn't
    finally:
        desk.chat._in_flight = 0
        desk.quit()
        desk.chat.close()
        desk.face.close()


def _wait(qapp, seconds):
    import time as _t

    end = _t.time() + seconds
    while _t.time() < end:
        qapp.processEvents()


def test_what_kit_says_sits_under_his_face_and_he_hops_up_for_room(qapp):
    from kit.desk.alive import Body

    face = desk_app.HelperFace(150)
    screen = face.screen().availableGeometry()
    face.show()
    face.put_face_at(desk_app.QPoint(screen.right() - 174, screen.bottom() - 154))  # the corner
    home = face.pos()
    body = Body(face, lambda: 150)
    bubble = desk_app.SpeechBubble(face, body)
    bubble.setText("Righto, the kettle's on.")
    _wait(qapp, 0.8)
    f = face.face_geometry()
    assert bubble.isVisible() and face.pos().y() < home.y()  # hopped up to make room
    assert bubble.y() >= f.top() + int(f.height() * 0.8)  # under his face, not over it
    assert bubble.geometry().bottom() <= screen.bottom()
    bubble.setText("")
    _wait(qapp, 0.8)
    assert not bubble.isVisible() and face.pos() == home  # settled back down
    bubble.idle_text = lambda: "watching the rain..."
    bubble.setText("")
    assert bubble.isVisible() and bubble.text() == "watching the rain..."
    bubble.hide()
    face.close()


def test_he_loops_when_excited_and_comes_home(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9", face_x=300, face_y=300).save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    desk.sounds.player = None
    try:
        home = desk.face.pos()
        assert desk.face.face_pos() == desk_app.QPoint(300, 300)  # where Dan left his face
        desk.face.face.set_emotion("excited", 0.0)
        assert desk.body.moving == "loop"
        _wait(qapp, 0.6)
        assert desk.face.pos() != home  # out on his loop
        _wait(qapp, 1.4)
        assert desk.body.moving is None and desk.face.pos() == home
        desk.face.face.play("bounce", 0.0)
        assert desk.body.moving is None  # too soon after the last move
        desk._moved_at.clear()
        desk.face.face.play("bounce", 0.0)
        assert desk.body.moving == "hop_hop"
        desk.body.stop()
        desk.config.movement = "a_little"
        desk.apply_look()
        desk._moved_at.clear()
        desk.face.face.play("bounce", 0.0)
        assert desk.body.moving is None and desk.face.face.amplitude == 1.0
    finally:
        desk.quit()
        desk.chat.close()
        desk.face.close()


def test_he_boops_when_he_talks_unless_told_not_to(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    played = []
    desk.sounds.player = lambda path: played.append(path.name)
    desk.performer.perform = lambda reply: None
    try:
        desk.show_chat()  # even with the chat open
        desk._act_out(reply_event("Hi")["reply"])
        assert played == ["boop-1.wav"] and desk.bubble.enabled
        desk._on_life({"type": "pipe_up", "reply": reply_event("Psst.")["reply"]})
        _wait(qapp, 1.0)
        assert played[-1] == "bip_boop-1.wav"
        desk.boop_action.setChecked(False)  # the tray switch
        assert DeskConfig.load(desk_dir).boop is False
        desk._act_out(reply_event("Quiet now")["reply"])
        assert len(played) == 2
    finally:
        desk.quit()
        desk.chat.close()
        desk.face.close()


def test_the_boop_is_a_short_wav():
    import io
    import wave

    from kit.desk.sound import SOUNDS, tone

    with wave.open(io.BytesIO(tone(SOUNDS["boop"]))) as w:
        assert w.getnchannels() == 1 and 0.1 < w.getnframes() / w.getframerate() < 0.3


def test_a_show_plays_as_he_answers(qapp, desk_dir, monkeypatch):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    desk.sounds.player = None
    desk.performer.perform = lambda reply: None
    time_show = {"kind": "time", "text": "3:07", "small": "pm"}
    try:
        desk._chat_state("heard")
        desk.chat.on_event(1, {"type": "show", "show": time_show})
        assert desk.face.scene is None  # waits for his answer
        desk.chat.on_event(1, reply_event("Just after three."))
        assert desk.face.scene is not None and desk.face.scene.show == time_show
        desk.face.scene = None
        desk.chat.on_event(1, {"type": "show", "show": time_show})  # a late one
        assert desk.face.scene is not None
    finally:
        desk.quit()
        desk.chat.close()
        desk.face.close()


LIFE = {
    "mood": "curious",
    "presence": "alone",
    "doing": "watching the rain",
    "energy": 0.8,
    "drives": {"boredom": 0.3, "curiosity": 0.55, "social": 0.6, "energy": 0.8},
    "dials": {"arousal": 0.7, "valence": 0.4},
    "feeling": {"name": "chuffed", "why": "Dan said thanks for the reminder"},
    "closeness": "good mates",
    "thinking": "Whether the cat likes rain.",
    "wants": ["the weather bet"],
}


def test_the_mood_page_shows_his_needs_and_cant_change_them(qapp, sync_window, tmp_path):
    from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QLineEdit, QSlider

    brain = FakeBrain()
    brain.life = lambda: LIFE
    win = make_window(sync_window, brain, tmp_path)
    win.show_page("Mood")
    page = win.mood
    assert page.mood.text() == "Curious"
    assert "watching the rain" in page.presence.text()
    assert "chuffed" in page.feeling.text() and "thanks" in page.feeling.text()
    bars = {name: bar.target for name, bar in page.bars.items()}
    assert bars["Energy"] == pytest.approx(0.8)
    assert bars["Fun"] == pytest.approx(0.7)  # not bored
    assert bars["Company"] == pytest.approx(0.4)  # wants company
    assert bars["Happiness"] == pytest.approx(0.7)
    assert page.face.face.emotion == "happy"  # chuffed
    assert 0.6 < page.gem.level < 0.7
    # Only to look at: nothing on the page can set a need.
    for kind in (QAbstractButton, QSlider, QAbstractSpinBox, QLineEdit):
        assert not page.findChildren(kind)
    brain.life = lambda: {**LIFE, "dials": None, "mood": "asleep", "feeling": None}
    page.refresh()
    assert "Happiness" not in page.bars and page.face.face.state == "sleeping"
    win.close()


def test_the_desk_draws_kit_from_the_brains_character_sheet():
    import copy

    import httpx

    from kit.desk.client import BrainClient
    from kit.face import character

    sheet = copy.deepcopy(character.builtin().sheet)
    sheet["looks"]["glow"]["colours"]["eye"] = "#FFB000"
    answers = {"/api/face": httpx.Response(200, json=sheet)}

    def brain(request):
        return answers.get(request.url.path, httpx.Response(404, json={"detail": "Not Found"}))

    client = BrainClient("http://kit-server:8600", "t", transport=httpx.MockTransport(brain))
    try:
        assert desk_app.load_character(client)
        assert character.current().look("desk")["colours"]["eye"] == "#FFB000"
        sheet["poses"]["happy"]["grin"] = 1  # a broken sheet keeps the face it had
        answers["/api/face"] = httpx.Response(200, json=sheet)
        assert not desk_app.load_character(client)
        assert character.current().look("desk")["colours"]["eye"] == "#FFB000"
        answers.clear()  # an older brain without /api/face
        assert not desk_app.load_character(client)
    finally:
        character.use(character.builtin())
        client.close()
