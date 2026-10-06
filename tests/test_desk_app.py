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


def test_glow_dozes_off_when_dan_is_away_and_wakes_when_he_is_back(qapp):
    from kit.desk.alive import Alive

    face = desk_app.HelperFace(150)
    face.move(400, 300)
    face.show()
    snap = {"idle_seconds": 5.0, "locked": False}
    looked = []
    alive = Alive(
        face, lambda: snap, lambda: looked.append(1) or (0, 0, 800, 600), lambda: 600, lambda: False
    )
    alive.step()
    assert not alive.asleep
    snap["idle_seconds"] = 700
    alive.step()
    assert alive.asleep and alive._awake_pos == face.pos()
    snap["idle_seconds"] = 1
    alive.step()
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
