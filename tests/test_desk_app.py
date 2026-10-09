"""The desk app's windows, run without a screen. Needs the desk extra."""

import os

import pytest

pytest.importorskip("PySide6.QtWidgets", reason="desk extra (PySide6) not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kit.desk import app as desk_app  # noqa: E402
from kit.desk.chat import ChatWindow  # noqa: E402
from kit.desk.config import DeskConfig, save_token  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


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
    assert "Claude (sonnet) · $0.010" in text


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


def test_glow_looks_where_kits_eyes_say_and_the_eyes_switch_reaches_the_brain(
    qapp, desk_dir, monkeypatch
):
    DeskConfig(brain_url="http://127.0.0.1:9").save(desk_dir)
    save_token("tok", desk_dir)
    monkeypatch.setattr(desk_app.DeskApp, "check_health", lambda self: None)
    desk = desk_app.DeskApp(qapp, background=True)
    try:
        desk._on_life({"type": "look", "x": -0.4, "y": 0.2})
        assert desk.face.face._look[:2] == (-0.4, 0.2)
        desk._on_life({"type": "state", "state": "asleep"})
        desk.face.face._look = None
        desk._on_life({"type": "look", "x": 0.3, "y": 0.0})
        assert desk.face.face._look is None  # asleep: no peeking
        assert desk.eyes_action.isChecked()
        desk._show_eyes(False)  # what the brain says, without switching anything
        assert not desk.eyes_action.isChecked()
        switched = []
        desk.client.set_eyes = lambda on: switched.append(on)
        desk.eyes_action.setChecked(True)
        import time as _t

        end = _t.time() + 2
        while not switched and _t.time() < end:
            qapp.processEvents()
            _t.sleep(0.02)
        assert switched == [True]
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
        assert desk.face.eye.name() == "#ffc66b" and desk.face.width() == 200
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


def test_updates_page_offers_a_newer_version(qapp, sync_window, tmp_path):
    from kit.desk.update import Release

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

    found = Release("0.1.0.99", "desk-v0.1.0.99", "New chat look", "", "", "K.exe", "u", 2, "")
    win = sync_window.KitWindow(
        DeskConfig(),
        "",
        "",
        lambda: None,
        lambda: "",
        tmp_path,
        updater=lambda c, t: FakeUpdater(found),
    )
    installs = []
    win.updates.install.connect(installs.append)
    win.show_page("Updates")
    win.updates.check()
    assert "0.1.0.99" in win.updates.status.text() and not win.updates.install_button.isHidden()
    win.updates.download()
    assert installs and installs[0].name == "K.exe"
    win.close()


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
