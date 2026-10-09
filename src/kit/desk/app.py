"""Kit's desk app for Windows: tray icon, Glow face, chat, and the desktop feed.

- Kit sits in the taskbar tray as his face. Click it (or the face) for the chat;
  right-click for the menu.
- Glow floats on screen, always on top, and can be dragged anywhere. He acts out
  each reply, says it in a speech bubble under his face (with a boop), and
  goes grey when he can't reach the brain.
- Every couple of seconds the app checks which windows are open and which has
  focus, and tells the brain when that changes (``kit.desk.watch``). Window
  titles and app names only, no screenshots. Watching can be paused from the
  menu.

The app connects out to the brain. The only thing it listens on is 127.0.0.1
(local to this PC) for Kit's Chrome extension (``kit.desk.browser``).
Run it with ``kit-desk`` (or ``python -m kit.desk``) after installing the
``desk`` extra, or install it with Kit-Desk-Setup.exe.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from kit.desk import face3d, startup, theme
from kit.desk.alive import Alive, Body
from kit.desk.browser import BrowserFeed, BrowserListener
from kit.desk.chat import ChatWindow
from kit.desk.client import BrainClient, BrainError
from kit.desk.config import UPDATE_TOKEN_FILE, DeskConfig, desk_dir, load_token, save_token
from kit.desk.face_preview import Performer
from kit.desk.glow import FaceWidget, paint_glow
from kit.desk.sound import Sounds
from kit.desk.update import CHECK_EVERY_S, FIRST_CHECK_S, VERSION, Updater, run_installer
from kit.desk.watch import OpenWindow, Reporter, WindowsDesktop, system_status
from kit.desk.window import ConnectionForm, KitWindow, in_background
from kit.face import Face, character
from kit.face.body import move_for
from kit.face.character import CharacterError

log = logging.getLogger("kit.desk")

INSTANCE_NAME = "kit-desk-app"
HEALTH_EVERY_MS = 15_000
OPEN_MS = 160  # the chat fades in this quickly
# Which DeskConfig fields each page of Kit's window owns, so a save on one page
# never puts back another page's old values.
PC_FIELDS = ("brain_url", "watch", "show_face", "hidden_apps", "hidden_words")
LOOK_FIELDS = (
    "theme",
    "accent",
    "eye_colour",
    "face_size",
    "font_pt",
    "speech_bubble",
    "boop",
    "movement",
)
# How much Kit moves (the Look page): (how big his gestures are, how big his
# whole-body moves are, 0 for none).
MOVEMENT = {
    "still": (0.6, 0.0),
    "a_little": (1.0, 0.0),
    "lively": (1.5, 1.0),
    "bouncy": (1.9, 1.35),
}
# Seconds before the same body move plays again, so he's lively, not frantic.
MOVE_AGAIN_S = {"loop": 40.0}
MOVE_GAP_S = 3.0  # between any two body moves
UPDATE_FIELDS = ("check_updates", "update_repo")
# What Kit's state reads as on the face while he works.
FACE_STATES = {
    "listening": "listening",
    "thinking": "thinking",
    "remembering": "thinking",
    "looking at your PC": "working",
    "speaking": "speaking",
}


def extension_folder() -> Path:
    """Kit's Chrome extension: beside Kit.exe once installed, else in the package."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "chrome-extension"
    return Path(__file__).parent / "browser_extension"


def load_character(client: BrainClient) -> bool:
    """Draw Kit from the brain's character sheet, so he looks and moves the same here
    as in home_app and on his robot screens, and a redesign needs no reinstall.
    Keeps the sheet built into this app if the brain is older or its sheet is broken."""
    try:
        character.use(character.from_sheet(client.face()))
    except BrainError as e:
        log.info("kept the built-in face: %s", e)
        return False
    except CharacterError as e:
        log.warning("the brain's character sheet is broken, kept the built-in face: %s", e)
        return False
    return True


def face_icon(offline: bool = False, size: int = 64, eye: str | None = None) -> QIcon:
    """Kit's face as an icon: the tray icon and the window icon."""
    face = Face()
    if offline:
        face.set_state("offline")
    frame = face.tick(0.0)
    frame = replace(frame, look_x=0.0, look_y=0.0, open_left=1.0, open_right=1.0)
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    paint_glow(p, QRectF(0, 0, size, size), frame, eye=QColor(eye) if eye else None)
    p.end()
    return QIcon(pix)


class HelperFace(FaceWidget):
    """Glow on the desktop: frameless, see-through, always on top. Drag to move;
    click to open the chat; right-click for the menu."""

    clicked = Signal()
    grabbed = Signal()  # Dan pressed on him (he may be about to be dragged)
    moved = Signal(QPoint)  # Dan dragged him here
    shifted = Signal()  # he moved, by any means

    # See-through room around his face for big gestures, so a tilt or a squash
    # isn't cut off at the window's edge. Clicks there go through to what's behind.
    MARGIN = 0.25

    def __init__(self, size: int) -> None:
        super().__init__()
        self.margin = self.MARGIN
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Kit")
        self.set_size(size)
        self._press: QPoint | None = None
        self._offset = QPoint()
        self.menu: QMenu | None = None

    def set_size(self, size: int) -> None:
        """His face ``size`` pixels across, keeping it where it is on screen."""
        side = round(size * (1 + 2 * self.margin))
        if side == self.width() == self.height():
            return
        centre = self.frameGeometry().center()
        self.resize(side, side)
        if self.isVisible():
            self.move(centre - self.rect().center())

    def face_geometry(self) -> QRect:
        """Where his face is on screen (the window less its see-through margin)."""
        return self.face_rect().toRect().translated(self.pos())

    def face_pos(self) -> QPoint:
        return self.face_geometry().topLeft()

    def put_face_at(self, pos: QPoint) -> None:
        """Move him so his face's top left is at ``pos``."""
        self.move(pos - self.face_rect().toRect().topLeft())

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.grabbed.emit()
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
            self.moved.emit(self.face_pos())

    def moveEvent(self, e) -> None:  # noqa: N802
        super().moveEvent(e)
        self.shifted.emit()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        if self.menu:
            self.menu.popup(e.globalPos())


class SpeechBubble(QLabel):
    """What Kit says, in a bubble just under his face. When the bottom of the
    screen leaves no room under him, he hops up a little while he talks and
    settles back afterwards. With nothing to say it shows what he's doing on his
    own (``idle_text``), if anything."""

    TAIL = 8  # how far the little point sticks up toward his face

    def __init__(
        self, face: HelperFace, body: Body, can_hop: Callable[[], bool] = lambda: True
    ) -> None:
        super().__init__()
        self.face = face
        self.body = body
        self.can_hop = can_hop
        self.enabled = True
        self.idle_text: Callable[[], str] = lambda: ""
        self._fill, self._edge = QColor("#0f141b"), QColor("#2b333f")
        self._above = False  # no room under him (asleep at the screen's edge)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWordWrap(True)
        self.restyle("#7ef3e6")
        face.shifted.connect(self._follow)

    def restyle(self, eye: str, font_pt: float = 10.0) -> None:
        """Glow's speech is in the colour of his eyes, on his own dark screen."""
        self._font_pt = font_pt
        self._eye = eye
        top, bottom = (8, 8 + self.TAIL) if self._above else (8 + self.TAIL, 8)
        self.setStyleSheet(
            f"QLabel {{ background: transparent; color: {eye};"
            f" padding: {top}px 12px {bottom}px 12px; font-size: {font_pt}pt; }}"
        )

    def setText(self, text: str) -> None:  # noqa: N802 (called by Performer)
        if not text:
            text = self.idle_text()  # back to what he's doing, if anything
        super().setText(text)
        if not text or not self.enabled or not self.face.isVisible():
            self.hide()
            self._settle()
            return
        self.ensurePolished()  # so the style sheet's font and padding are measured
        one_line = self.fontMetrics().horizontalAdvance(text) + 32
        self.setFixedWidth(min(one_line, 300))
        self.adjustSize()
        self._place(hop=True)
        self.show()
        self.raise_()

    def _place(self, hop: bool = False) -> None:
        f = self.face.face_geometry()
        screen = self.face.screen().availableGeometry()
        # The face's dark screen ends 83% of the way down.
        y = f.top() + int(f.height() * 0.84)
        short = y + self.height() - screen.bottom()
        above = False
        if short > 0:
            if hop and self.can_hop():
                self.body.lift(self.body.lifted + short + 4)  # placed again as he rises
            if not self.body.lift_to and not self.can_hop():
                above = True  # asleep on the screen's edge: say it over his head
                y = f.top() + int(f.height() * 0.15) - self.height()
            else:
                y = screen.bottom() - self.height()  # mid-hop
        if above != self._above:
            self._above = above
            self.restyle(self._eye, self._font_pt)
            self.adjustSize()
        x = f.center().x() - self.width() // 2
        x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        self.move(x, y)
        self.update()

    def _follow(self) -> None:
        if self.isVisible():
            self._place()

    def _settle(self) -> None:
        """Back down to where Dan left him."""
        if self.body.lift_to:
            self.body.lift(0)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t = self.TAIL
        body = r.adjusted(0, 0, 0, -t) if self._above else r.adjusted(0, t, 0, 0)
        path = QPainterPath()
        path.addRoundedRect(body, 14, 14)
        # The point aims at his face, wherever the bubble had to sit.
        tip_x = self.face.face_geometry().center().x() - self.x()
        tip_x = max(body.left() + 18, min(tip_x, body.right() - 18))
        tail = QPainterPath()
        if self._above:
            tail.moveTo(tip_x - t, body.bottom() - 1)
            tail.lineTo(tip_x, r.bottom())
            tail.lineTo(tip_x + t, body.bottom() - 1)
        else:
            tail.moveTo(tip_x - t, body.top() + 1)
            tail.lineTo(tip_x, r.top())
            tail.lineTo(tip_x + t, body.top() + 1)
        tail.closeSubpath()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(self._edge, 1))
        p.setBrush(self._fill)
        p.drawPath(path.united(tail))
        p.end()
        super().paintEvent(event)


class SettingsDialog(QDialog):
    """The first-run setup: where the brain is, the token, and what Kit may see.
    Afterwards the same form is the This PC page of Kit's window."""

    def __init__(self, config: DeskConfig, token: str, first_run: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Kit setup" if first_run else "Kit settings")
        self.setWindowIcon(face_icon())
        self.form = ConnectionForm(config, token, first_run)
        # The form's boxes, by name, for callers and tests.
        for name in ("url", "token", "watch", "hidden_apps", "hidden_words", "show_face"):
            setattr(self, name, getattr(self.form, name))
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
        layout.addWidget(self.form)
        layout.addWidget(buttons)
        self.resize(560, 0)

    def values(self) -> tuple[DeskConfig, str, bool]:
        return self.form.values()


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

    def focused_rect(self) -> tuple[int, int, int, int] | None:
        return None


class _Signals(QObject):
    online = Signal(bool, str)
    life = Signal(dict)
    character = Signal()


class DeskApp(QObject):
    def __init__(self, app: QApplication, background: bool) -> None:
        super().__init__()
        self.app = app
        self.config = DeskConfig.load()
        self.token = load_token()
        self.update_token = load_token(name=UPDATE_TOKEN_FILE)
        self.client: BrainClient | None = None
        self._face_from: tuple | None = None  # (brain, character) whose sheet is in use
        self.online: bool | None = None
        self._doing = ""  # what Kit's doing on his own, shown in his bubble
        self._quiet = ""  # why he's keeping quiet, shown in the tray's tooltip
        self._stop = threading.Event()
        self._signals = _Signals()
        self._signals.online.connect(self._show_online)
        self._signals.life.connect(self._on_life)
        self._signals.character.connect(self._use_look)
        self._face3d: face3d.Face3D | None = None  # the 3D face page over Glow, if his look is 3D

        self.face = HelperFace(self.config.face_size)
        self.face.setWindowIcon(face_icon())
        self.body = Body(self.face, lambda: self.config.face_size)
        self.face.grabbed.connect(lambda: self.body.stop(go_home=False))
        self.face.face.on_play = lambda gesture, _now: self._move(gesture=gesture)
        self.face.face.on_emotion = lambda emotion, _now: self._move(emotion=emotion)
        self._moved_at: dict[str, float] = {}
        self.bubble = SpeechBubble(self.face, self.body, lambda: not self._asleep())
        self.bubble.idle_text = lambda: f"{self._doing}..." if self._doing else ""
        self.sounds = Sounds(desk_dir() / "sounds")
        self._next_sound = "boop"
        self.performer = Performer(self.face, self.bubble)
        self.chat = ChatWindow()
        self.chat.setWindowIcon(face_icon())
        self.chat.resize(self.config.chat_width, self.config.chat_height)
        self.chat.replied.connect(self._act_out)
        self.chat.shown.connect(self._show)
        self._showing: dict | None = None  # a show waiting for his answer to start
        self._answered = False  # he's answered the message just sent
        self.chat.state.connect(self._chat_state)
        self.chat.settings_wanted.connect(lambda: self.open_window("Kit's settings"))
        self.chat.resized.connect(self._chat_resized)
        self._save_soon = QTimer(self)
        self._save_soon.setSingleShot(True)
        self._save_soon.timeout.connect(lambda: self.config.save())
        self.window: KitWindow | None = None
        self.apply_look()

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

        self.browser = BrowserFeed()
        self.listener: BrowserListener | None = None
        try:
            self.listener = BrowserListener(self.browser, lambda: self.config.watch)
            self.listener.start()
        except OSError:
            log.exception("can't listen for the Chrome extension (is another Kit running?)")
        desktop = WindowsDesktop() if sys.platform == "win32" else _NoDesktop()
        self.reporter = Reporter(
            desktop, self._report, lambda: self.config, system_status, browser=self.browser.current
        )
        self.alive = Alive(self.face, desktop.focused_rect, self._busy, body=self.body)
        self.health = QTimer(self)
        self.health.timeout.connect(self.check_health)
        self.health.start(HEALTH_EVERY_MS)
        self.check_health()
        threading.Thread(target=self._watch_loop, name="kit-watch", daemon=True).start()
        threading.Thread(target=self._life_loop, name="kit-life", daemon=True).start()
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.check_for_update)
        self.update_timer.start(FIRST_CHECK_S * 1000)

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
        self.playing_action = QAction("Share what's playing", menu, checkable=True)
        self.playing_action.setChecked(self.config.share_playing)
        self.playing_action.toggled.connect(self.set_sharing_playing)
        menu.addAction(self.playing_action)
        self.boop_action = QAction("Boop when Kit talks", menu, checkable=True)
        self.boop_action.setChecked(self.config.boop)
        self.boop_action.toggled.connect(self.set_boop)
        menu.addAction(self.boop_action)
        menu.addSeparator()
        menu.addAction("How Kit's feeling...", lambda: self.open_window("Mood"))
        menu.addAction("What Kit remembers...", lambda: self.open_window("Memory"))
        menu.addAction("Settings...", lambda: self.open_window("Kit's settings"))
        menu.addAction("Look...", lambda: self.open_window("Look"))
        menu.addAction("Quiet for an hour", lambda: self.quiet(60))
        menu.addSeparator()
        menu.addAction("Kit in the browser", lambda: webbrowser.open(self.config.brain_url))
        menu.addAction("Set up the Chrome extension...", self.extension_help)
        menu.addAction("Check for updates...", lambda: self.open_window("Updates", check=True))
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
        self.chat.load_history()
        if not self.chat.isVisible():
            self._fade_in(self.chat)
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat.input.setFocus()

    def _fade_in(self, window: QWidget) -> None:
        window.setWindowOpacity(0.0)
        fade = QPropertyAnimation(window, b"windowOpacity", window)
        fade.setDuration(OPEN_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _chat_resized(self, size) -> None:
        if (size.width(), size.height()) != (self.config.chat_width, self.config.chat_height):
            self.config.chat_width, self.config.chat_height = size.width(), size.height()
            self._save_soon.start(800)

    def _place_chat(self) -> None:
        """Open the chat beside Kit's face, on whichever side has room."""
        screen = (self.face.screen() or self.app.primaryScreen()).availableGeometry()
        f = self.face.face_geometry()
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
        self.face.put_face_at(QPoint(x, y))

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

    def set_sharing_playing(self, on: bool) -> None:
        self.config.share_playing = on
        self.config.save()
        self.tray.showMessage(
            "Kit",
            "I'll keep an ear on what's playing." if on else "Okay, I won't listen in.",
            face_icon(),
            2500,
        )

    def set_boop(self, on: bool) -> None:
        if on == self.config.boop:
            return
        self.config.boop = on
        self.config.save()
        if self.window is not None:
            self.window.look.show_boop(on)
        if on:
            self.sounds.play("boop")

    def open_settings(self, first_run: bool = False) -> None:
        if not first_run:
            self.open_window("This PC")
            return
        dialog = SettingsDialog(self.config, self.token, first_run)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if not self.token:
                QMessageBox.information(
                    None, "Kit", "Kit needs its address and token. Open Settings from the tray."
                )
            return
        self.save_pc(*dialog.values())

    def save_pc(self, config: DeskConfig, token: str, at_logon: bool) -> None:
        """This PC's settings, from the first-run setup or the This PC page."""
        self._take(config, PC_FIELDS)
        self.token = token
        save_token(self.token)
        try:
            startup.set_enabled(at_logon)
        except OSError:
            log.exception("changing start at logon failed")
        self.face_action.setChecked(self.config.show_face)
        self.watch_action.setChecked(self.config.watch)
        self._connect()
        self.check_health()

    def _take(self, config: DeskConfig, names: tuple[str, ...]) -> None:
        """Keep a page's fields from ``config`` and save."""
        self.config = replace(self.config, **{n: getattr(config, n) for n in names})
        self.config.save()

    # Kit's window: memory, settings, look, updates

    def open_window(self, page: str = "Memory", check: bool = False) -> None:
        if self.window is None:
            self.window = KitWindow(
                self.config,
                self.token,
                self.update_token,
                lambda: self.client,
                lambda: self.config.brain_url,
                desk_dir() / "updates",
            )
            self.window.setWindowIcon(face_icon(eye=self.config.eye_colour))
            self.window.apply_look(self._palette(), self.config.font_pt)
            self.window.mood.face.eye = QColor(self.config.eye_colour)
            self.window.pc.saved.connect(self.save_pc)
            self.window.look.changed.connect(self.set_look)
            self.window.updates.settings_changed.connect(self._update_settings)
            self.window.updates.install.connect(self.install_update)
        if not self.window.isVisible():
            self._fade_in(self.window)
        self.window.show_page(page)
        if check:
            self.window.updates.check()

    def _palette(self) -> theme.Palette:
        return theme.palette(self.config.theme, self.config.accent)

    def set_look(self, config: DeskConfig) -> None:
        self._take(config, LOOK_FIELDS)
        self.boop_action.setChecked(self.config.boop)
        self.apply_look()

    def apply_look(self) -> None:
        """Show the Look page's choices everywhere: chat, window, face and bubble."""
        palette = self._palette()
        self.chat.apply_look(palette, self.config.font_pt)
        if self.window is not None:
            self.window.apply_look(palette, self.config.font_pt)
            self.window.mood.face.eye = QColor(self.config.eye_colour)
        self.face.eye = QColor(self.config.eye_colour)
        self.face.set_size(self.config.face_size)
        amplitude, self.body.scale = MOVEMENT.get(self.config.movement, MOVEMENT["lively"])
        self.face.face.amplitude = amplitude
        self.bubble.restyle(self.config.eye_colour, max(8.0, self.config.font_pt - 0.5))
        icon = face_icon(eye=self.config.eye_colour)
        self.chat.setWindowIcon(icon)
        if self.online and hasattr(self, "tray"):
            self.tray.setIcon(icon)

    # Updates

    def _update_settings(self, config: DeskConfig, token: str) -> None:
        self._take(config, UPDATE_FIELDS)
        if token != self.update_token:
            self.update_token = token
            save_token(token, name=UPDATE_TOKEN_FILE)

    def check_for_update(self) -> None:
        """The daily check. A newer version is offered, never installed unasked."""
        self.update_timer.start(CHECK_EVERY_S * 1000)
        if not self.config.check_updates:
            return
        updater = Updater(self.config.update_repo, self.update_token)

        def done(found) -> None:
            updater.close()
            if isinstance(found, Exception):
                log.info("update check: %s", found)
                return
            if found is None:
                return
            log.info("update %s is available (this is %s)", found.version, VERSION)
            self.open_window("Updates")
            self.window.updates.show_release(found)
            self.tray.showMessage(
                "Kit", f"A new version of me is ready ({found.version}).", face_icon(), 8000
            )

        in_background(updater.newer, done)

    def install_update(self, installer) -> None:
        try:
            run_installer(installer)
        except Exception as e:  # noqa: BLE001 (shown to Dan)
            QMessageBox.warning(None, "Kit", f"The update didn't start: {e}")
            return
        log.info("installing %s", installer)
        self.quit()

    def extension_help(self) -> None:
        folder = extension_folder()
        state = (
            "It's connected and sending your tabs."
            if self.browser.connected
            else "It isn't connected yet."
        )
        QMessageBox.information(
            None,
            "Kit's Chrome extension",
            f"{state}\n\nTo add it: open chrome://extensions in Chrome (or edge://extensions "
            "in Edge), turn on Developer mode, choose Load unpacked, and pick this folder:\n\n"
            f"{folder}\n\nThe folder opens when you press OK.",
        )
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 (opens the folder in Explorer)
        else:
            webbrowser.open(folder.as_uri())

    def quit(self) -> None:
        self._stop.set()
        if self.listener:
            self.listener.stop()
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
                return
            # Fetch his character sheet on connecting and whenever face.character changes.
            key = (client, status.get("face"))
            if key != self._face_from:
                self._face_from = key
                load_character(client)
                self._signals.character.emit()

        threading.Thread(target=work, name="kit-health", daemon=True).start()

    def _use_look(self) -> None:
        """Draw his desk look: Glow, or the brain's 3D face page over it."""
        look = character.current().look("desk", ("glow", "model"))
        url = self.client.url if self.client is not None else None
        self._face3d = face3d.sync(self.face, url, look, self._face3d)

    def _show_online(self, online: bool, detail: str) -> None:
        if online != self.online:
            self.tray.setIcon(face_icon(offline=not online, eye=self.config.eye_colour))
            self.face.face.set_state("idle" if online else "offline")
            if self.online is not None:
                log.info("brain %s: %s", "online" if online else "offline", detail)
        self.online = online
        tip = "Kit" if online else f"Kit is offline: {detail}"
        if online and self._quiet:
            tip += f"\nQuiet: {self._quiet}"
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

    # Kit's inner life (kit.life on the brain decides; this acts it out)

    def _life_loop(self) -> None:
        after: int | None = None
        while not self._stop.is_set():
            client = self.client
            if client is None:
                self._stop.wait(5)
                continue
            try:
                if after is None:  # start from now, not from old fidgets
                    state = client.life()
                    after = state["last_event"]
                    if state.get("mood") == "asleep":
                        self._signals.life.emit({"type": "state", "state": "asleep"})
                got = client.life_events(after)
                for event in got["events"]:
                    self._signals.life.emit(event)
                after = got["events"][-1]["id"] if got["events"] else max(after, 0)
                if got["last"] < after:  # the brain restarted: its event ids began again
                    after = None
            except (BrainError, KeyError, TypeError):
                after = None
                self._stop.wait(10)

    def _on_life(self, event: dict) -> None:
        face = self.face.face
        if event.get("type") == "state":
            if event.get("state") == "asleep":
                self.alive.fall_asleep()
            elif event.get("state") == "awake":
                self.alive.wake_up()
        elif event.get("type") == "fidget":
            if not self._busy() and not self.alive.asleep:
                face.play(event.get("gesture", "look_away"), time.monotonic())
        elif event.get("type") == "react":  # a reaction plays even mid-conversation
            if not self.alive.asleep:
                face.play(event.get("gesture", "perk_up"), time.monotonic())
        elif event.get("type") == "doing":  # what he's up to while you're out
            self._doing = str(event.get("what") or "")
            self._show_doing()
        elif event.get("type") == "dials":
            face.set_dials(float(event.get("arousal", 0.5)), float(event.get("valence", 0.0)))
        elif event.get("type") == "quiet":  # why he's keeping quiet, in the tray's tooltip
            self._quiet = str(event.get("because") or "")
            if self.online:
                self._show_online(True, "online")
        elif event.get("type") == "pipe_up":
            reply = event.get("reply") or {}
            if self.alive.asleep:
                self.alive.wake_up()
            face.play("perk_up", time.monotonic())
            self._next_sound = "bip_boop"  # he started this one himself
            if event.get("reason") == "back":  # Dan's home: a happy loop
                QTimer.singleShot(400, lambda: self._move(reason="back"))
            QTimer.singleShot(700, lambda: self.chat.on_event(0, {"type": "reply", "reply": reply}))
            if not self.face.isVisible() and not self.chat.isVisible():
                said = " ".join(s.get("say", "") for s in reply.get("segments", []))
                self.tray.showMessage("Kit", said, face_icon(), 8000)

    def _show_doing(self) -> None:
        """What Kit's doing on his own ("watching the rain...") in his bubble, while
        he isn't saying anything."""
        if self._busy() or not self.config.speech_bubble:
            return
        self.bubble.enabled = True
        self.bubble.setText("")  # an empty bubble shows what he's doing (``idle_text``)

    def _move(self, gesture: str = "", emotion: str = "", reason: str = "") -> None:
        """A whole-body move to go with a gesture, an emotion or a reason, if one
        does (kit.face.body): a loop when he's excited, a hop, a jump back."""
        name = move_for(gesture, emotion, reason)
        if name is None or self._asleep() or self.face.face.state == "offline":
            return
        now = time.monotonic()
        last = max(self._moved_at.values(), default=-1e9)
        again = self._moved_at.get(name, -1e9) + MOVE_AGAIN_S.get(name, 0.0)
        if not reason and (now - last < MOVE_GAP_S or now < again):
            return
        if self.body.moving is None and self.body.scale > 0:
            self._moved_at[name] = now
            self.body.play(name)

    def _asleep(self) -> bool:
        return hasattr(self, "alive") and self.alive.asleep

    def _busy(self) -> bool:
        return self.chat._in_flight > 0 or self.face.face.state in (
            "speaking",
            "thinking",
            "working",
        )

    def quiet(self, minutes: float) -> None:
        client = self.client
        if client is None:
            return
        threading.Thread(
            target=lambda: _quietly(client.snooze, minutes), name="kit-snooze", daemon=True
        ).start()
        self.tray.showMessage("Kit", "Righto, zipping it for an hour.", face_icon(), 2500)

    # The face

    def _chat_state(self, state: str) -> None:
        if self.online is False:
            return
        if state in FACE_STATES:
            if state != "speaking":  # speaking is set by the performer, word by word
                self.face.face.set_state(FACE_STATES[state])
        elif state == "heard":  # a little nod as a message goes, before he thinks
            self.face.face.play("nod", time.monotonic())
            self._showing, self._answered = None, False
        elif state == "error":
            self.face.face.play("shrug", time.monotonic())
        elif state.startswith("asking"):
            self.face.face.set_state("working")
        elif state == "idle" and self.face.face.state != "speaking":
            self.face.face.set_state("idle")

    def _act_out(self, reply: dict) -> None:
        """Kit said something: he acts it out, says it under his face, and boops."""
        self.bubble.enabled = self.config.speech_bubble
        sound, self._next_sound = self._next_sound, "boop"
        if not reply.get("segments"):
            return
        if self.config.boop:
            self.sounds.play(sound)
        self.performer.perform(reply)
        self._answered = True
        if self._showing is not None:
            self.face.play_show(self._showing)
            self._showing = None

    def _show(self, show: dict) -> None:
        """Something for his face to show (the time, the weather). It plays as he
        answers, so the time is up while he says it; a late one plays at once."""
        if self._answered:
            self.face.play_show(show)
        else:
            self._showing = show


def _quietly(call, *args) -> None:
    try:
        call(*args)
    except BrainError:
        log.exception("telling Kit to be quiet failed")


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


def _selftest(argv: list[str]) -> int:
    """Prove a built exe has everything it needs (Qt plugins, the face), then exit.
    The installer build runs this before packaging."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    face3d.prepare()
    app = QApplication(argv[:1])
    if face_icon().isNull():
        return 2
    chat = ChatWindow()
    chat.on_event(1, {"type": "say", "text": "**Self-test.**"})
    window = KitWindow(DeskConfig(), "", "", lambda: None, lambda: "", desk_dir() / "updates")
    ok = "Self-test." in chat.text() and QLocalServer is not None and window is not None
    ok = ok and face3d.available()  # the 3D face needs Qt's web engine packed in
    app.quit()
    return 0 if ok else 3


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--version" in argv:
        print(f"Kit desk app {VERSION}")
        return 0
    if "--selftest" in argv:
        return _selftest(argv)
    _log_to_file()
    face3d.prepare()
    app = QApplication(argv)
    app.setApplicationName("Kit")
    app.setQuitOnLastWindowClosed(False)  # closing the chat leaves Kit in the tray
    server = _single_instance()
    if server is None:
        return 0
    desk = DeskApp(app, background="--background" in argv)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), desk.show_chat()))
    log.info("Kit desk app %s started", VERSION)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
