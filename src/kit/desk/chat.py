"""The desk app's chat window: talk to Kit, see his replies stream in.

It shows the same events as the brain's web chat page (kit/web/chat.html), as
rounded bubbles: Dan's on the right in the accent colour, Kit's on the left with
markdown (bold, lists, code, tables, links). New bubbles fade and slide in, and
the view stays pinned to the newest message while Dan is at the bottom; if he
scrolls up to read, it stays put and a "Latest" button appears instead.

Calls to the brain run on worker threads and come back through Qt signals, so
the window never freezes while Kit thinks. Each finished reply is handed to the
app, which has the face act it out.
"""

from __future__ import annotations

import itertools
import re
import threading
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QKeyEvent, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from kit.desk import theme
from kit.desk.client import BrainClient, BrainError

MAX_SHOWN = 200
BUBBLE_SHARE = 0.8  # a bubble is at most this share of the window's width
STICK_PX = 40  # this close to the bottom counts as "at the bottom"
FADE_MS = 220
LINK_COLOUR = re.compile(r"color:#0000ff;", re.IGNORECASE)  # Qt's default link blue
BODY_STYLE = re.compile(r"<body style=\"[^\"]*\">")
PAD_X = 14  # a bubble's padding either side of its text
INPUT_LINES = (1, 6)  # the message box grows from one line to six as Dan types


@dataclass
class Line:
    role: str  # you, kit, claude, note or error
    text: str
    detail: str = ""
    meta: list[str] = field(default_factory=list)


class Bubble(QFrame):
    """One message. Kit's text is markdown; Dan's is shown as typed."""

    def __init__(self, line: Line, palette: theme.Palette) -> None:
        super().__init__()
        self.setObjectName("bubble")
        self.role = line.role
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.body.setOpenExternalLinks(True)
        self.body.setTextFormat(
            Qt.TextFormat.PlainText if line.role == "you" else Qt.TextFormat.RichText
        )
        self.link = ""
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.meta = QLabel()
        self.meta.setObjectName("meta")
        self.text = ""
        self.limit = 10_000  # the widest this bubble may be, set by Row.fit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X, 9, PAD_X, 9)
        layout.setSpacing(6)
        layout.addWidget(self.body)
        layout.addWidget(self.detail)
        layout.addWidget(self.meta)
        self.restyle(palette)
        self.set_line(line)

    def restyle(self, palette: theme.Palette) -> None:
        self.setStyleSheet(theme.bubble_style(palette, self.role))
        small = self.font()
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        self.meta.setFont(small)
        mono = self.font()
        mono.setFamilies(["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
        mono.setPointSizeF(max(7.0, mono.pointSizeF() - 1.0))
        self.detail.setFont(mono)
        self.detail.setStyleSheet(
            f"background: {palette.code}; color: {palette.text}; border-radius: 8px;"
            " padding: 6px 8px;"
        )
        # Links in the accent colour, lightened on dark bubbles so they stay readable.
        link = QColor(palette.accent)
        self.link = (link.lighter(150) if palette.dark else link).name()
        if self.text:
            self.body.setText(self._html(self.text))

    def set_line(self, line: Line) -> None:
        self.text = line.text
        self.body.setText(self._html(line.text))
        self.body.setVisible(bool(line.text))
        self.detail.setText(line.detail)
        self.detail.setVisible(bool(line.detail))
        self.meta.setText(" · ".join(line.meta))
        self.meta.setVisible(bool(line.meta))
        self.fit(self.limit)

    def _html(self, text: str) -> str:
        """Kit's markdown as HTML with links in the theme's colour (a label's link
        colour can't be set from a style sheet)."""
        if self.role == "you" or not text:
            return text
        doc = QTextDocument()
        doc.setMarkdown(text)
        html = BODY_STYLE.sub("<body>", doc.toHtml())  # take the window's font and size
        return LINK_COLOUR.sub(f"color:{self.link};", html)

    def fit(self, limit: int) -> None:
        """Be as wide as the text needs, up to ``limit``. A word-wrapped label would
        otherwise pick a narrow width and wrap short messages early."""
        self.limit = limit
        self.setMaximumWidth(limit)
        room = limit - 2 * PAD_X - 4
        widest = max(self._natural(self.body, self.text), self._natural(self.detail, ""))
        self.body.setMinimumWidth(min(widest, room))

    def _natural(self, label: QLabel, text: str) -> int:
        text = text or label.text()
        if not text or label.isHidden() and label is not self.body:
            return 0
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        label.ensurePolished()
        doc.setDefaultFont(label.font())
        if label is self.body and self.role != "you":
            doc.setMarkdown(text)
        else:
            doc.setPlainText(text)
        extra = 20 if label is self.detail else 2  # the detail box's own padding
        return int(doc.idealWidth()) + extra


class Row(QWidget):
    """A bubble pushed to its side, or a centred note."""

    def __init__(self, line: Line, palette: theme.Palette) -> None:
        super().__init__()
        self.line = line
        self.bubble: Bubble | None = None
        self.note: QLabel | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        if line.role in ("note", "error"):
            self.note = QLabel(line.text)
            self.note.setWordWrap(True)
            self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.note, 1)
        else:
            self.bubble = Bubble(line, palette)
            self.bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            if line.role == "you":
                layout.addStretch(1)
            layout.addWidget(self.bubble)
            if line.role != "you":
                layout.addStretch(1)
        self.restyle(palette)

    def restyle(self, palette: theme.Palette) -> None:
        if self.note is not None:
            colour = palette.error if self.line.role == "error" else palette.muted
            self.note.setStyleSheet(f"color: {colour}; background: transparent;")
        if self.bubble is not None:
            self.bubble.restyle(palette)

    def update_line(self, line: Line) -> None:
        self.line = line
        if self.bubble is not None:
            self.bubble.set_line(line)
        elif self.note is not None:
            self.note.setText(line.text)

    def fit(self, width: int) -> None:
        if self.bubble is not None:
            self.bubble.fit(max(160, int(width * BUBBLE_SHARE)))


class Typing(QFrame):
    """Three dots that rise in turn while Kit thinks."""

    def __init__(self, palette: theme.Palette) -> None:
        super().__init__()
        self.setObjectName("bubble")
        self.dots = [QLabel("●") for _ in range(3)]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)
        for d in self.dots:
            layout.addWidget(d)
        self._step = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.restyle(palette)

    def restyle(self, palette: theme.Palette) -> None:
        self._palette = palette
        self.setStyleSheet(theme.bubble_style(palette, "kit"))
        self._tick()

    def start(self) -> None:
        self._timer.start(260)

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._step = (self._step + 1) % 3
        for i, d in enumerate(self.dots):
            colour = self._palette.text if i == self._step else self._palette.muted
            d.setStyleSheet(f"color: {colour}; font-size: 8pt; background: transparent;")


class _Signals(QObject):
    event = Signal(int, dict)
    done = Signal(int)
    history = Signal(list)


class ChatWindow(QWidget):
    """Kit's chat. ``replied`` carries each finished reply for the face to act out;
    ``state`` carries what Kit is doing ("thinking", "speaking", "idle"...).
    ``settings_wanted`` asks the app to open Kit's window; ``resized`` reports the
    new size so it can be remembered."""

    replied = Signal(dict)
    state = Signal(str)
    settings_wanted = Signal()
    resized = Signal(QSize)

    def __init__(
        self,
        client: BrainClient | None = None,
        palette: theme.Palette | None = None,
        font_pt: float = 10.5,
    ) -> None:
        super().__init__()
        self.client = client
        self.palette = palette or theme.palette()
        self.font_pt = font_pt
        self.setObjectName("root")
        self.setWindowTitle("Kit")
        self.setMinimumSize(340, 420)
        self.resize(460, 640)
        self.lines: list[Line] = []
        self.rows: list[Row] = []
        self._current: dict[int, int] = {}  # turn -> index of Kit's line being streamed
        self._turns = itertools.count(1)
        self._in_flight = 0
        self._loaded = False
        self._replace = False
        self._stick = True
        self._signals = _Signals()
        self._signals.event.connect(self.on_event)
        self._signals.done.connect(self._turn_done)
        self._signals.history.connect(self._show_history)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        # Header: who and what he's doing, a fresh start, and Kit's window.
        self.title = QLabel("Kit")
        self.title.setObjectName("title")
        self.status = QLabel("idle")
        self.status.setObjectName("status")
        fresh = QPushButton("New chat")
        fresh.setObjectName("flat")
        fresh.setToolTip("Start a fresh conversation. Kit still remembers this one.")
        fresh.clicked.connect(self.new_chat)
        gear = QPushButton("⚙")
        gear.setObjectName("flat")
        gear.setToolTip("Memory, settings and how Kit looks")
        gear.clicked.connect(self.settings_wanted.emit)
        bar = QFrame()
        bar.setObjectName("bar")
        top = QHBoxLayout(bar)
        top.setContentsMargins(16, 10, 10, 10)
        top.addWidget(self.title)
        top.addSpacing(8)
        top.addWidget(self.status, 1)
        top.addWidget(fresh)
        top.addWidget(gear)

        # The conversation.
        self.body = QWidget()
        self.body.setObjectName("scrollBody")
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(0, 12, 0, 12)
        self.column.setSpacing(4)
        self.column.addStretch(1)
        self.typing = Typing(self.palette)
        self.typing_row = QWidget()
        typing_layout = QHBoxLayout(self.typing_row)
        typing_layout.setContentsMargins(12, 3, 12, 3)
        typing_layout.addWidget(self.typing)
        typing_layout.addStretch(1)
        self.typing_row.hide()
        self.column.addWidget(self.typing_row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body)
        scrollbar = self.scroll.verticalScrollBar()
        scrollbar.valueChanged.connect(self._scrolled)
        scrollbar.rangeChanged.connect(self._range_changed)
        self.jump = QPushButton("↓ Latest", self.scroll)
        self.jump.setObjectName("jump")
        self.jump.clicked.connect(lambda: self.scroll_to_end(animate=True))
        self.jump.hide()

        # The message box grows as Dan types; Enter sends, Shift+Enter is a new line.
        self.input = QPlainTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText("Message Kit")
        self.input.setToolTip("Enter sends, Shift+Enter starts a new line")
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.document().setDocumentMargin(2)
        self.input.installEventFilter(self)
        self.input.textChanged.connect(self._grow_input)
        send = QPushButton("↑")
        send.setObjectName("send")
        send.setToolTip("Send (Enter)")
        send.clicked.connect(self.submit)
        foot = QFrame()
        foot.setObjectName("bar")
        row = QHBoxLayout(foot)
        row.setContentsMargins(12, 10, 6, 10)
        row.setSpacing(8)
        row.addWidget(self.input, 1)
        row.addWidget(send, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(QSizeGrip(foot), 0, Qt.AlignmentFlag.AlignBottom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self._rule())
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self._rule())
        layout.addWidget(foot)
        self.apply_look(self.palette, font_pt)

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("barLine")
        return line

    # Look

    def apply_look(self, palette: theme.Palette, font_pt: float) -> None:
        """Restyle everything, for a change on the Look page."""
        self.palette, self.font_pt = palette, font_pt
        self.setStyleSheet(theme.window_style(palette, font_pt))
        width = self.scroll.viewport().width()
        for row in self.rows:
            row.restyle(palette)
            row.fit(width)
        self.typing.restyle(palette)
        self._grow_input()

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
        self._stick = True  # sending always brings the newest message into view
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

    def new_chat(self) -> None:
        """Start a fresh conversation; the old one stays in Kit's memory."""
        client = self.client
        if client is None:
            return
        try:
            client.new_chat()
        except BrainError as e:
            self._add(Line("error", str(e)))
            return
        self._set_lines([])

    def load_history(self) -> None:
        """Show the recent conversation each time the window opens, so a new chat
        started elsewhere (the chat page, ``kit new-chat``) shows here too. Not while
        Kit is still answering, so a streaming reply isn't swept away."""
        if self.client is None or self._in_flight:
            return
        self._replace = self._loaded  # first time: keep anything already shown
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
        lines = old if self._replace and not self._in_flight else old + self.lines
        if [(x.role, x.text) for x in lines] == [(x.role, x.text) for x in self.lines]:
            return  # nothing new: leave the view (and Dan's scroll position) alone
        self._stick = True
        self._set_lines(lines)

    def on_event(self, turn: int, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "say":
            role = "claude" if ev.get("source") == "cloud" else "kit"
            if turn not in self._current:
                self._current[turn] = self._add(Line(role, ""))
            index = self._current[turn]
            self.lines[index].text += ev.get("text", "")
            self.rows[index].update_line(self.lines[index])
            self._set_state("speaking")
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
                index = self._current.pop(turn)
                self.lines[index] = line
                self.rows[index].update_line(line)
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
        elif kind == "new_topic":  # the brain left the old conversation behind
            self._add(Line("note", ev.get("message") or "New topic, so Kit started fresh."))
        elif kind == "error":
            self._add(Line("error", ev.get("message", "Something went wrong.")))
            self.state.emit("error")
        self._show_typing()

    def _turn_done(self, turn: int) -> None:
        self._current.pop(turn, None)
        self._in_flight = max(0, self._in_flight - 1)
        if self._in_flight == 0:
            self._set_state("idle")
        self._show_typing()

    def _set_state(self, text: str) -> None:
        self.status.setText(text)
        self.state.emit(text)
        self._show_typing()

    def _show_typing(self) -> None:
        """The dots show while Kit is working on an answer he hasn't started saying."""
        waiting = self._in_flight > 0 and not self._current
        if waiting and self.typing_row.isHidden():
            self.typing_row.show()
            self.typing.start()
        elif not waiting and not self.typing_row.isHidden():
            self.typing_row.hide()
            self.typing.stop()

    def _add(self, line: Line, animate: bool = True) -> int:
        self.lines.append(line)
        row = Row(line, self.palette)
        row.fit(self.scroll.viewport().width())
        self.rows.append(row)
        self.column.insertWidget(self.column.count() - 1, row)  # above the typing dots
        row.fit(self.scroll.viewport().width())  # again, now it has the window's font
        if len(self.lines) > MAX_SHOWN:
            drop = len(self.lines) - MAX_SHOWN
            for old in self.rows[:drop]:
                old.deleteLater()
            self.lines, self.rows = self.lines[drop:], self.rows[drop:]
            self._current = {t: i - drop for t, i in self._current.items() if i >= drop}
        if animate and self.isVisible():
            self._fade_in(row)
        return len(self.lines) - 1

    def _set_lines(self, lines: list[Line]) -> None:
        for row in self.rows:
            self.column.removeWidget(row)
            row.deleteLater()
        self.lines, self.rows, self._current = [], [], {}
        for line in lines[-MAX_SHOWN:]:
            self._add(line, animate=False)
        QTimer.singleShot(0, self.scroll_to_end)

    def _fade_in(self, row: Row) -> None:
        """A new bubble fades in while rising a few pixels into place."""
        effect = QGraphicsOpacityEffect(row)
        effect.setOpacity(0.0)
        row.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", row)
        fade.setDuration(FADE_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(row)
        group.addAnimation(fade)
        if row.bubble is not None:
            rise = QPropertyAnimation(row.bubble, b"pos", row)
            rise.setDuration(FADE_MS)
            rise.setEasingCurve(QEasingCurve.Type.OutCubic)
            QTimer.singleShot(0, lambda: _start_rise(rise, row.bubble))
        # A finished opacity effect would keep drawing the row through an off-screen
        # buffer (blurry text on some screens), so it's removed once done.
        group.finished.connect(lambda: row.setGraphicsEffect(None))
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)

    # Scrolling: stay at the bottom while Dan is there.

    def _scrolled(self, value: int) -> None:
        bar = self.scroll.verticalScrollBar()
        self._stick = value >= bar.maximum() - STICK_PX
        if self._stick:
            self.jump.hide()

    def _range_changed(self, _low: int, high: int) -> None:
        if self._stick:
            self.scroll.verticalScrollBar().setValue(high)
        elif self.lines:
            self._place_jump()
            self.jump.show()
            self.jump.raise_()

    def scroll_to_end(self, animate: bool = False) -> None:
        bar = self.scroll.verticalScrollBar()
        self._stick = True
        self.jump.hide()
        if not animate:
            bar.setValue(bar.maximum())
            return
        glide = QPropertyAnimation(bar, b"value", self)
        glide.setDuration(260)
        glide.setStartValue(bar.value())
        glide.setEndValue(bar.maximum())
        glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        glide.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def at_bottom(self) -> bool:
        return self._stick

    def _place_jump(self) -> None:
        self.jump.adjustSize()
        view = self.scroll.viewport().geometry()
        self.jump.move(
            view.center().x() - self.jump.width() // 2, view.bottom() - self.jump.height() - 10
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        width = self.scroll.viewport().width()
        for row in self.rows:
            row.fit(width)
        self._place_jump()
        self.resized.emit(self.size())

    def _grow_input(self) -> None:
        lines = int(self.input.document().documentLayout().documentSize().height()) or 1
        lines = max(INPUT_LINES[0], min(INPUT_LINES[1], lines))
        step = self.input.fontMetrics().lineSpacing()
        self.input.setFixedHeight(lines * step + 30)  # padding, margins and border
        bar = Qt.ScrollBarPolicy
        over = int(self.input.document().documentLayout().documentSize().height()) > lines
        self.input.setVerticalScrollBarPolicy(
            bar.ScrollBarAsNeeded if over else bar.ScrollBarAlwaysOff
        )

    def text(self) -> str:
        """Everything shown, as plain text (for tests)."""
        parts = []
        for line in self.lines:
            parts.append(line.text)
            if line.detail:
                parts.append(line.detail)
            if line.meta:
                parts.append(" · ".join(line.meta))
        return "\n".join(parts)


def _start_rise(rise: QPropertyAnimation, bubble: QWidget) -> None:
    """Once the layout has placed the bubble, slide it up into that spot."""
    end = bubble.pos()
    rise.setStartValue(end + QPoint(0, 10))
    rise.setEndValue(end)
    rise.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
