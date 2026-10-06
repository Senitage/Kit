"""The desk app's chat window: talk to Kit, see his replies stream in.

It shows the same events as the brain's web chat page (kit/web/chat.html).
Calls to the brain run on worker threads and come back through Qt signals, so
the window never freezes while Kit thinks. Each finished reply is handed to the
app, which has the face act it out.
"""

from __future__ import annotations

import html
import itertools
import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from kit.desk.client import BrainClient, BrainError

MAX_SHOWN = 200
STYLE = """
body { font-family: 'Segoe UI', sans-serif; font-size: 10.5pt; }
.you { color: #e6edf3; background: #1f6feb; }
.kit { color: #e6edf3; background: #21262d; }
.claude { color: #e6edf3; background: #3b2e58; }
.note { color: #8b949e; }
.error { color: #ff7b72; }
.meta { color: #8b949e; font-size: 8.5pt; }
pre { font-family: Consolas, monospace; font-size: 9pt; color: #c9d1d9; }
"""


@dataclass
class Line:
    role: str  # you, kit, claude, note or error
    text: str
    detail: str = ""
    meta: list[str] = field(default_factory=list)


def _bubble(line: Line) -> str:
    text = html.escape(line.text).replace("\n", "<br>")
    if line.role in ("note", "error"):
        return f'<p class="{line.role}">{text}</p>'
    align = "right" if line.role == "you" else "left"
    detail = f"<pre>{html.escape(line.detail)}</pre>" if line.detail else ""
    meta = (
        f'<br><span class="meta">{html.escape(" · ".join(line.meta))}</span>' if line.meta else ""
    )
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td align="{align}">'
        f'<table cellpadding="8" class="{line.role}"><tr><td>{text}{detail}{meta}'
        f"</td></tr></table></td></tr></table><p></p>"
    )


class _Signals(QObject):
    event = Signal(int, dict)
    done = Signal(int)
    history = Signal(list)


class ChatWindow(QWidget):
    """Kit's chat. ``replied`` carries each finished reply for the face to act out;
    ``state`` carries what Kit is doing ("thinking", "speaking", "idle"...)."""

    replied = Signal(dict)
    state = Signal(str)

    def __init__(self, client: BrainClient | None = None) -> None:
        super().__init__()
        self.client = client
        self.setWindowTitle("Kit")
        self.resize(440, 600)
        self.lines: list[Line] = []
        self._current: dict[int, int] = {}  # turn -> index of Kit's line being streamed
        self._turns = itertools.count(1)
        self._in_flight = 0
        self._loaded = False
        self._signals = _Signals()
        self._signals.event.connect(self.on_event)
        self._signals.done.connect(self._turn_done)
        self._signals.history.connect(self._show_history)

        self.status = QLabel("idle")
        self.status.setStyleSheet("color: #8b949e;")
        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(True)
        self.log.document().setDefaultStyleSheet(STYLE)
        self.setStyleSheet(
            "ChatWindow, QTextBrowser { background: #0d1117; border: none; }"
            "QPlainTextEdit { background: #161b22; color: #e6edf3; border: 1px solid #30363d;"
            " border-radius: 6px; padding: 4px; }"
            "QPushButton { background: #238636; color: white; border: none; border-radius: 6px;"
            " padding: 8px 14px; }"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Talk to Kit (Enter sends, Shift+Enter for a new line)")
        self.input.setFixedHeight(64)
        self.input.installEventFilter(self)
        send = QPushButton("Send")
        send.clicked.connect(self.submit)

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(send)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.log, 1)
        layout.addLayout(row)

    # Sending

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt's name)
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key: QKeyEvent = event
            enter = key.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            if enter and not key.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.submit()
                return True
        return super().eventFilter(obj, event)

    def submit(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.send(text)

    def send(self, text: str) -> int:
        """Ask Kit something. Kit can be asked again before he answers."""
        turn = next(self._turns)
        self._add(Line("you", text))
        self._in_flight += 1
        self._set_state("thinking")
        client = self.client
        if client is None:
            self.on_event(
                turn, {"type": "error", "message": "Kit isn't set up yet: open Settings."}
            )
            self._turn_done(turn)
            return turn

        def work() -> None:
            try:
                for event in client.chat(text):
                    self._signals.event.emit(turn, event)
            except BrainError as e:
                self._signals.event.emit(turn, {"type": "error", "message": str(e)})
            finally:
                self._signals.done.emit(turn)

        threading.Thread(target=work, name=f"kit-chat-{turn}", daemon=True).start()
        return turn

    def load_history(self) -> None:
        """Show the recent conversation, once, the first time the window opens."""
        if self._loaded or self.client is None:
            return
        self._loaded = True
        client = self.client

        def work() -> None:
            try:
                self._signals.history.emit(client.messages(40))
            except BrainError as e:
                self._signals.history.emit([{"role": "error", "text": str(e)}])

        threading.Thread(target=work, name="kit-history", daemon=True).start()

    def set_client(self, client: BrainClient | None) -> None:
        self.client = client
        self._loaded = False

    # Showing

    def _show_history(self, messages: list) -> None:
        old = []
        for m in messages:
            if m.get("role") == "user":
                old.append(Line("you", m.get("text", "")))
            elif m.get("role") == "error":
                old.append(Line("error", m.get("text", "")))
            else:
                reply = m.get("reply") or {}
                role = "claude" if m.get("source") == "cloud" else "kit"
                old.append(Line(role, m.get("text", ""), reply.get("detail", "")))
        self.lines = old + self.lines
        self._render()

    def on_event(self, turn: int, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "say":
            role = "claude" if ev.get("source") == "cloud" else "kit"
            if turn not in self._current:
                self._current[turn] = self._add(Line(role, ""), render=False)
            self.lines[self._current[turn]].text += ev.get("text", "")
            self._set_state("speaking")
            self._render()
        elif kind == "reply":
            reply = ev.get("reply") or {}
            text = " ".join(s.get("say", "") for s in reply.get("segments", []))
            cloud = ev.get("source") == "cloud"
            line = Line("claude" if cloud else "kit", text, reply.get("detail", ""))
            if cloud:
                line.meta = [f"{ev.get('label')} ({ev.get('model')})"]
                if "cost_usd" in ev:
                    line.meta.append(f"${ev['cost_usd']:.3f}")
                if ev.get("searches"):
                    line.meta.append(f"{ev['searches']} searches")
            if turn in self._current:
                self.lines[self._current.pop(turn)] = line
                self._render()
            else:
                self._add(line)
            self.replied.emit(reply)
        elif kind == "handing_off":
            self._current.pop(turn, None)
            self._set_state(f"asking {ev.get('to', 'the cloud')}")
        elif kind == "recalled":
            self._current.pop(turn, None)
            self._set_state("remembering")
        elif kind == "looked_at_pc":
            self._current.pop(turn, None)
            self._set_state("looking at your PC")
        elif kind == "notice":
            self._current.pop(turn, None)
            self._add(Line("note", ev.get("message", "")))
        elif kind == "remembered":
            label = {"same": "Already knew", "update": "Updated memory"}.get(
                ev.get("decision"), "Remembered"
            )
            self._add(Line("note", f"{label}: {ev.get('fact', '')}"))
        elif kind == "thing_suggested":
            thing = ev.get("thing") or {}
            self._add(Line("note", f"Add to the register? {thing.get('line', '')} (yes or no)"))
        elif kind == "thing_updated" and ev.get("thing"):
            self._add(Line("note", f"Updated the register: {ev['thing'].get('line', '')}"))
        elif kind == "error":
            self._add(Line("error", ev.get("message", "Something went wrong.")))
            self.state.emit("error")

    def _turn_done(self, turn: int) -> None:
        self._current.pop(turn, None)
        self._in_flight = max(0, self._in_flight - 1)
        if self._in_flight == 0:
            self._set_state("idle")

    def _set_state(self, text: str) -> None:
        self.status.setText(text)
        self.state.emit(text)

    def _add(self, line: Line, render: bool = True) -> int:
        self.lines.append(line)
        if len(self.lines) > MAX_SHOWN:
            drop = len(self.lines) - MAX_SHOWN
            self.lines = self.lines[drop:]
            self._current = {t: i - drop for t, i in self._current.items() if i >= drop}
        if render:
            self._render()
        return len(self.lines) - 1

    def _render(self) -> None:
        self.log.setHtml("".join(_bubble(line) for line in self.lines))
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def text(self) -> str:
        """Everything shown, as plain text (for tests)."""
        return self.log.toPlainText()
