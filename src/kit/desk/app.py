"""Kit's desk app for Windows: tray icon, Glow face, chat, and the desktop feed.

- Kit sits in the taskbar tray as his face. Click it (or the face) for the chat;
  right-click for the menu.
- Glow floats on screen, always on top, and can be dragged anywhere. He acts out
  each reply, says it in a little speech bubble when the chat is closed, and
  goes grey when he can't reach the brain.
- Every couple of seconds the app checks which windows are open and which has
  focus, and tells the brain when that changes (``kit.desk.watch``). Window
  titles and app names only, no screenshots. Watching can be paused from the
  menu.

The app only connects out to the brain, so nothing here listens on the network.
Run it with ``kit-desk`` (or ``python -m kit.desk``) after installing the
``desk`` extra, or install it with Kit-Desk-Setup.exe.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import time
import webbrowser
from dataclasses import replace

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QMouseEvent, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import kit
from kit.desk import startup
from kit.desk.chat import ChatWindow
from kit.desk.client import BrainClient, BrainError
from kit.desk.config import DeskConfig, desk_dir, load_token, save_token
from kit.desk.face_preview import Performer
from kit.desk.glow import FaceWidget, paint_glow
from kit.desk.watch import OpenWindow, Reporter, WindowsDesktop, system_status
from kit.face import Face

log = logging.getLogger("kit.desk")

INSTANCE_NAME = "kit-desk-app"
HEALTH_EVERY_MS = 15_000
# What Kit's state reads as on the face while he works.
FACE_STATES = {
    "thinking": "thinking",
    "remembering": "thinking",
    "looking at your PC": "working",
    "speaking": "speaking",
}


def face_icon(offline: bool = False, size: int = 64) -> QIcon:
    """Kit's face as an icon: the tray icon and the window icon."""
    face = Face()
    if offline:
        face.set_state("offline")
    frame = face.tick(0.0)
    frame = replace(frame, look_x=0.0, look_y=0.0, open_left=1.0, open_right=1.0)
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    paint_glow(p, QRectF(0, 0, size, size), frame)
    p.end()
    return QIcon(pix)


class HelperFace(FaceWidget):
    """Glow on the desktop: frameless, see-through, always on top. Drag to move;
    click to open the chat; right-click for the menu."""

    clicked = Signal()
    moved = Signal(QPoint)

    def __init__(self, size: int) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Kit")
        self.resize(size, size)
        self._press: QPoint | None = None
        self._offset = QPoint()
        self.menu: QMenu | None = None

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._offset = self._press - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._press is not None:
            self.move(e.globalPosition().toPoint() - self._offset)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._press is None:
            return
        travelled = (e.globalPosition().toPoint() - self._press).manhattanLength()
        self._press = None
        if travelled < 5:
            self.clicked.emit()
        else:
            self.moved.emit(self.pos())

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        if self.menu:
            self.menu.popup(e.globalPos())


class SpeechBubble(QLabel):
    """What Kit says, shown under his face while the chat is closed."""

    def __init__(self, face: QWidget) -> None:
        super().__init__()
        self.face = face
        self.enabled = True
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWordWrap(True)
        self.setStyleSheet(
            "QLabel { background: #0f141b; color: #7ef3e6; border: 1px solid #2b333f;"
            " border-radius: 10px; padding: 8px 10px; font-size: 10pt; }"
        )

    def setText(self, text: str) -> None:  # noqa: N802 (called by Performer)
        super().setText(text)
        if not text or not self.enabled or not self.face.isVisible():
            self.hide()
            return
        self.ensurePolished()  # so the style sheet's font and padding are measured
        one_line = self.fontMetrics().horizontalAdvance(text) + 32
        self.setFixedWidth(min(one_line, 280))
        self.adjustSize()
        f = self.face.frameGeometry()
        x = f.center().x() - self.width() // 2
        y = f.bottom() + 4
        screen = self.face.screen().availableGeometry()
        if y + self.height() > screen.bottom():
            y = f.top() - self.height() - 4
        x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        self.move(x, y)
        self.show()


class SettingsDialog(QDialog):
    """Where the brain is, the token, and what Kit may see. Also the first-run setup."""

    def __init__(self, config: DeskConfig, token: str, first_run: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Kit setup" if first_run else "Kit settings")
        self.setWindowIcon(face_icon())
        self.config = config
        self.url = QLineEdit(config.brain_url)
        self.url.setPlaceholderText("http://kit-server:8600")
        self.token = QLineEdit(token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("run `kit token` on the server")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        test = QPushButton("Test connection")
        test.clicked.connect(self.test)
        self.watch = QCheckBox("Let Kit see which windows are open and what I'm working on")
        self.watch.setChecked(config.watch)
        self.show_face = QCheckBox("Show Kit's face on the desktop")
        self.show_face.setChecked(config.show_face)
        self.at_logon = QCheckBox("Start Kit when I log on")
        self.at_logon.setChecked(startup.enabled() or first_run)
        self.at_logon.setEnabled(sys.platform == "win32")
        self.hidden_apps = QLineEdit(", ".join(config.hidden_apps))
        self.hidden_words = QPlainTextEdit(", ".join(config.hidden_words))
        self.hidden_words.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("Kit's address", self.url)
        form.addRow("Token", self.token)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(self.result, 1)
        form.addRow("", row)
        form.addRow(self.watch)
        form.addRow("Never share titles from", self.hidden_apps)
        form.addRow("or titles with the words", self.hidden_words)
        form.addRow(self.show_face)
        form.addRow(self.at_logon)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        if first_run:
            intro = QLabel(
                "Kit's brain runs on the server. Enter its address (the same one you use "
                "for Kit's chat page) and the token from `kit token`."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(520, 0)

    def test(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        client = BrainClient(self.url.text().strip(), self.token.text().strip())
        try:
            status = client.check()
            self.result.setText(
                f"Connected to {status.get('name', 'Kit')} {status.get('version')}."
            )
            self.result.setStyleSheet("color: #3fb950;")
        except BrainError as e:
            self.result.setText(str(e))
            self.result.setStyleSheet("color: #f85149;")
        finally:
            client.close()
            QApplication.restoreOverrideCursor()

    @staticmethod
    def _list(text: str) -> list[str]:
        return [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]

    def values(self) -> tuple[DeskConfig, str, bool]:
        config = replace(
            self.config,
            brain_url=self.url.text().strip().rstrip("/") or self.config.brain_url,
            watch=self.watch.isChecked(),
            show_face=self.show_face.isChecked(),
            hidden_apps=self._list(self.hidden_apps.text()),
            hidden_words=self._list(self.hidden_words.toPlainText()),
        )
        return config, self.token.text().strip(), self.at_logon.isChecked()


class _NoDesktop:
    """Off Windows there's no window list; the app still reports PC health."""

    def windows(self) -> list[OpenWindow]:
        return []

    def focused(self) -> OpenWindow | None:
        return None

    def idle_seconds(self) -> float:
        return 0.0

    def locked(self) -> bool:
        return False


class _Signals(QObject):
    online = Signal(bool, str)


class DeskApp(QObject):
    def __init__(self, app: QApplication, background: bool) -> None:
        super().__init__()
        self.app = app
        self.config = DeskConfig.load()
        self.token = load_token()
        self.client: BrainClient | None = None
        self.online: bool | None = None
        self._stop = threading.Event()
        self._signals = _Signals()
        self._signals.online.connect(self._show_online)

        self.face = HelperFace(self.config.face_size)
        self.face.setWindowIcon(face_icon())
        self.bubble = SpeechBubble(self.face)
        self.performer = Performer(self.face, self.bubble)
        self.chat = ChatWindow()
        self.chat.setWindowIcon(face_icon())
        self.chat.replied.connect(self._act_out)
        self.chat.state.connect(self._chat_state)

        self.menu = self._menu()
        self.face.menu = self.menu
        self.face.clicked.connect(self.toggle_chat)
        self.face.moved.connect(self._face_moved)
        self.tray = QSystemTrayIcon(face_icon(offline=True))
        self.tray.setToolTip("Kit: connecting")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()

        self._connect()
        self._place_face()
        if self.config.show_face:
            self.face.show()

        desktop = WindowsDesktop() if sys.platform == "win32" else _NoDesktop()
        self.reporter = Reporter(desktop, self._report, lambda: self.config, system_status)
        self.health = QTimer(self)
        self.health.timeout.connect(self.check_health)
        self.health.start(HEALTH_EVERY_MS)
        self.check_health()
        threading.Thread(target=self._watch_loop, name="kit-watch", daemon=True).start()

        if not self.token:
            QTimer.singleShot(0, lambda: self.open_settings(first_run=True))
        elif not background:
            self.tray.showMessage("Kit", "I'm down here in the tray.", face_icon(), 3000)

    # Menu and windows

    def _menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("Open chat", self.show_chat)
        self.face_action = QAction("Show Kit's face", menu, checkable=True)
        self.face_action.setChecked(self.config.show_face)
        self.face_action.toggled.connect(self.set_face_shown)
        menu.addAction(self.face_action)
        self.watch_action = QAction("Share what I'm working on", menu, checkable=True)
        self.watch_action.setChecked(self.config.watch)
        self.watch_action.toggled.connect(self.set_watching)
        menu.addAction(self.watch_action)
        menu.addSeparator()
        menu.addAction("Kit in the browser", lambda: webbrowser.open(self.config.brain_url))
        menu.addAction(
            "What Kit remembers", lambda: webbrowser.open(self.config.brain_url + "/memory")
        )
        menu.addAction("Settings...", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit Kit", self.quit)
        return menu

    def _tray_clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_chat()

    def toggle_chat(self) -> None:
        if self.chat.isVisible() and self.chat.isActiveWindow():
            self.chat.hide()
        else:
            self.show_chat()

    def show_chat(self) -> None:
        if not self.chat.isVisible():
            self._place_chat()
        self.bubble.hide()
        self.chat.load_history()
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat.input.setFocus()

    def _place_chat(self) -> None:
        """Open the chat beside Kit's face, on whichever side has room."""
        screen = (self.face.screen() or self.app.primaryScreen()).availableGeometry()
        f = self.face.frameGeometry()
        w, h = self.chat.width(), self.chat.height()
        x = f.left() - w - 8 if f.left() - w - 8 >= screen.left() else f.right() + 8
        y = max(screen.top(), min(f.bottom() - h, screen.bottom() - h))
        self.chat.move(max(screen.left(), min(x, screen.right() - w)), y)

    def _place_face(self) -> None:
        screen = self.app.primaryScreen().availableGeometry()
        size = self.config.face_size
        x, y = self.config.face_x, self.config.face_y
        on_screen = (
            x is not None
            and y is not None
            and any(
                s.availableGeometry().contains(QPoint(x + size // 2, y + size // 2))
                for s in self.app.screens()
            )
        )
        if not on_screen:  # first run, or the monitor it was on has gone
            x, y = screen.right() - size - 24, screen.bottom() - size - 24
        self.face.move(x, y)

    def _face_moved(self, pos: QPoint) -> None:
        self.config.face_x, self.config.face_y = pos.x(), pos.y()
        self.config.save()

    def set_face_shown(self, on: bool) -> None:
        self.config.show_face = on
        self.config.save()
        self.face.setVisible(on)
        if not on:
            self.bubble.hide()

    def set_watching(self, on: bool) -> None:
        self.config.watch = on
        self.config.save()
        self.tray.showMessage(
            "Kit",
            "I can see what you're working on again."
            if on
            else "Okay, I've stopped looking at your windows.",
            face_icon(),
            2500,
        )

    def open_settings(self, first_run: bool = False) -> None:
        dialog = SettingsDialog(self.config, self.token, first_run)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if first_run and not self.token:
                QMessageBox.information(
                    None, "Kit", "Kit needs its address and token. Open Settings from the tray."
                )
            return
        self.config, self.token, at_logon = dialog.values()
        self.config.save()
        save_token(self.token)
        try:
            startup.set_enabled(at_logon)
        except OSError:
            log.exception("changing start at logon failed")
        self.face_action.setChecked(self.config.show_face)
        self.watch_action.setChecked(self.config.watch)
        self._connect()
        self.check_health()

    def quit(self) -> None:
        self._stop.set()
        self.tray.hide()
        self.app.quit()

    # The brain

    def _connect(self) -> None:
        old = self.client
        self.client = BrainClient(self.config.brain_url, self.token) if self.token else None
        self.chat.set_client(self.client)
        if old:
            old.close()

    def check_health(self) -> None:
        client = self.client
        if client is None:
            self._show_online(False, "not set up yet: open Settings")
            return

        def work() -> None:
            try:
                status = client.check()
                self._signals.online.emit(True, status.get("pc") or "online")
            except BrainError as e:
                self._signals.online.emit(False, str(e))

        threading.Thread(target=work, name="kit-health", daemon=True).start()

    def _show_online(self, online: bool, detail: str) -> None:
        if online != self.online:
            self.tray.setIcon(face_icon(offline=not online))
            self.face.face.set_state("idle" if online else "offline")
            if self.online is not None:
                log.info("brain %s: %s", "online" if online else "offline", detail)
        self.online = online
        tip = "Kit" if online else f"Kit is offline: {detail}"
        if self.reporter.error and online:
            tip += f"\nCan't send what you're working on: {self.reporter.error}"
        self.tray.setToolTip(tip[:120])

    def _report(self, snapshot: dict) -> None:
        if self.client is None:
            raise BrainError("not set up yet")
        self.client.report(snapshot)

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.reporter.tick()
            except Exception:
                log.exception("watching the desktop failed")
            self._stop.wait(max(0.5, self.config.poll_seconds))

    # The face

    def _chat_state(self, state: str) -> None:
        if self.online is False:
            return
        if state in FACE_STATES:
            if state != "speaking":  # speaking is set by the performer, word by word
                self.face.face.set_state(FACE_STATES[state])
        elif state == "error":
            self.face.face.play("shrug", time.monotonic())
        elif state.startswith("asking"):
            self.face.face.set_state("working")
        elif state == "idle" and self.face.face.state != "speaking":
            self.face.face.set_state("idle")

    def _act_out(self, reply: dict) -> None:
        self.bubble.enabled = not self.chat.isVisible()
        if reply.get("segments"):
            self.performer.perform(reply)


def _single_instance() -> QLocalServer | None:
    """Only one Kit per logon: a second launch just opens the first one's chat."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return None
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer()
    server.listen(INSTANCE_NAME)
    return server


def _log_to_file() -> None:
    folder = desk_dir()
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        folder / "desk.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--version" in argv:
        print(f"Kit desk app {kit.__version__}")
        return 0
    _log_to_file()
    app = QApplication(argv)
    app.setApplicationName("Kit")
    app.setQuitOnLastWindowClosed(False)  # closing the chat leaves Kit in the tray
    server = _single_instance()
    if server is None:
        return 0
    desk = DeskApp(app, background="--background" in argv)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), desk.show_chat()))
    log.info("Kit desk app %s started", kit.__version__)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
