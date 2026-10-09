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
from datetime import datetime

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
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
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
    meta: list[tuple[str, str]] = field(default_factory=list)  # shown on a click
    tier: str = "chat"  # which model answered (theme.TIERS), for the bubble's colour


ROLE_NAMES = {"chat": "Chat", "work": "Work", "expert": "Expert"}


def tier_of(meta: dict | None) -> str:
    """Which model answered a reply: chat (local or cloud), work or expert."""
    role = (meta or {}).get("role")
    return role if role in theme.TIERS else "chat"


def when(at: str | None = None, now: datetime | None = None) -> str:
    """A message's time, with the day when it wasn't today."""
    now = now or datetime.now()
    try:
        then = datetime.fromisoformat(at) if at else now
    except ValueError:
        return ""
    if then.date() == now.date():
        return then.strftime("%H:%M")
    return then.strftime("%a %d %b, %H:%M")


def details(meta: dict | None, source: str | None, at: str | None = None) -> list[tuple]:
    """What the details panel shows for one of Kit's replies: who answered, as what,
    what it cost and when."""
    m = meta or {}
    rows: list[tuple[str, str]] = []
    if m.get("model"):
        rows.append(("Answered by", m.get("label") or m["model"]))
        if m.get("label") and m["label"] != m["model"]:
            rows.append(("Model", m["model"]))
    elif source in (None, "local"):
        rows.append(("Answered by", "Kit's local model"))
    rows.append(("As", ROLE_NAMES[tier_of(m)]))
    if source == "pipe_up":
        rows.append(("Said", "on his own"))
    if "cost_usd" in m:
        rows.append(("Cost", f"${m['cost_usd']:.3f}"))
    if m.get("searches"):
        rows.append(("Web searches", str(m["searches"])))
    if "month_usd" in m:
        rows.append(("This month", f"${m['month_usd']:.2f}"))
    if stamp := when(at):
        rows.append(("Time", stamp))
    return rows


class Bubble(QFrame):
    """One message. Kit's text is markdown; Dan's is shown as typed."""

    clicked = Signal()

    def __init__(self, line: Line, palette: theme.Palette) -> None:
        super().__init__()
        self.setObjectName("bubble")
        self.role = line.role
        self.tier = line.tier
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.body.setOpenExternalLinks(True)
        self.body.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # the row's menu
        self.body.setTextFormat(
            Qt.TextFormat.PlainText if line.role == "you" else Qt.TextFormat.RichText
        )
        self.link = ""
        self._on_link = False  # a click on a link opens it, not the details
        self.body.linkHovered.connect(lambda url: setattr(self, "_on_link", bool(url)))
        self.body.installEventFilter(self)
        if line.role != "you":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Click for details")
        self.text = ""
        self.limit = 10_000  # the widest this bubble may be, set by Row.fit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD_X, 9, PAD_X, 9)
        layout.setSpacing(6)
        layout.addWidget(self.body)
        self.restyle(palette)
        self.set_line(line)

    def restyle(self, palette: theme.Palette) -> None:
        self._palette = palette
        self.setStyleSheet(theme.bubble_style(palette, self.role, self.tier))
        # Links in the accent colour, lightened on dark bubbles so they stay readable.
        link = QColor(palette.accent)
        self.link = (link.lighter(150) if palette.dark else link).name()
        if self.text:
            self.body.setText(self._html(self.text))

    def set_line(self, line: Line) -> None:
        # A reply's written detail (steps, code, paths) follows what Kit said in the
        # same bubble, so it reads as one message rather than a second voice.
        self.text = message_text(line)
        self.body.setText(self._html(self.text))
        self.body.setVisible(bool(self.text))
        if line.tier != self.tier:
            self.tier = line.tier
            self.setStyleSheet(theme.bubble_style(self._palette, self.role, self.tier))
        self.fit(self.limit)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt's name)
        # The text takes the clicks (to select and follow links), so a plain click on
        # it counts as a click on the bubble.
        if obj is self.body and event.type() == QEvent.Type.MouseButtonRelease:
            self._release(event)
        return super().eventFilter(obj, event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        self._release(event)
        super().mouseReleaseEvent(event)

    def _release(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._on_link:
            return
        if not self.body.hasSelectedText():
            self.clicked.emit()

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
        self.body.setMinimumWidth(min(self._natural(), room))

    def _natural(self) -> int:
        if not self.text:
            return 0
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        self.body.ensurePolished()
        doc.setDefaultFont(self.body.font())
        if self.role == "you":
            doc.setPlainText(self.text)
        else:
            doc.setMarkdown(self.text)
        return int(doc.idealWidth()) + 2


def message_text(line: Line) -> str:
    """A message as shown and as copied: what was said, then any written detail."""
    if line.detail.strip():
        return f"{line.text}\n\n{line.detail.strip()}" if line.text else line.detail.strip()
    return line.text


SPEAKER = {"you": "Me", "kit": "Kit", "claude": "Kit (via Claude)"}


def transcript(lines: list[Line]) -> str:
    """The conversation as plain text, ready to paste into another chat."""
    parts = []
    for line in lines:
        if line.role in SPEAKER:
            parts.append(f"{SPEAKER[line.role]}: {message_text(line)}")
        elif line.text:
            parts.append(f"[{line.text}]")
    return "\n\n".join(parts)


class Row(QWidget):
    """A bubble pushed to its side, or a centred note. Hovering shows a Copy button
    beside the bubble; right-click offers copying the message or the conversation."""

    copied = Signal(str)  # text to put on the clipboard
    copy_all = Signal()
    opened = Signal(object)  # this row: show its details

    def __init__(self, line: Line, palette: theme.Palette) -> None:
        super().__init__()
        self.line = line
        self.bubble: Bubble | None = None
        self.note: QLabel | None = None
        self.copy = QPushButton("Copy")
        self.copy.setObjectName("flat")
        self.copy.setToolTip("Copy this message")
        self.copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy.clicked.connect(lambda: self.copied.emit(message_text(self.line)))
        keep = self.copy.sizePolicy()
        keep.setRetainSizeWhenHidden(True)  # so the bubble doesn't shift on hover
        self.copy.setSizePolicy(keep)
        self.copy.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(4)
        if line.role in ("note", "error"):
            self.note = QLabel(line.text)
            self.note.setWordWrap(True)
            self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.note, 1)
        else:
            self.bubble = Bubble(line, palette)
            if line.role != "you":
                self.bubble.clicked.connect(lambda: self.opened.emit(self))
            self.bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            if line.role == "you":
                layout.addStretch(1)
                layout.addWidget(self.copy, 0, Qt.AlignmentFlag.AlignVCenter)
                layout.addWidget(self.bubble)
            else:
                layout.addWidget(self.bubble)
                layout.addWidget(self.copy, 0, Qt.AlignmentFlag.AlignVCenter)
                layout.addStretch(1)
        self.restyle(palette)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        if self.bubble is not None:
            self.copy.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        self.copy.hide()
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        menu = QMenu(self)
        picked = self.bubble.body.selectedText() if self.bubble is not None else ""
        if picked:
            menu.addAction("Copy selection", lambda: self.copied.emit(picked))
        menu.addAction("Copy message", lambda: self.copied.emit(message_text(self.line)))
        menu.addAction("Copy whole conversation", self.copy_all.emit)
        menu.exec(event.globalPos())

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


class Details(QWidget):
    """A reply's details in a small panel that pops out beside the chat window,
    level with the bubble. Clicking anywhere else closes it."""

    GAP = 8

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.card = QFrame()
        self.card.setObjectName("details")
        self.grid = QGridLayout(self.card)
        self.grid.setContentsMargins(14, 12, 14, 12)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(5)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)

    def fill(self, rows: list[tuple[str, str]], palette: theme.Palette) -> None:
        self.card.setStyleSheet(theme.details_style(palette))
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        title = QLabel("Details")
        title.setObjectName("title")
        self.grid.addWidget(title, 0, 0, 1, 2)
        for i, (name, value) in enumerate(rows or [("", "Nothing more to show")], start=1):
            label = QLabel(name)
            label.setObjectName("muted")
            shown = QLabel(value)
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(label, i, 0)
            self.grid.addWidget(shown, i, 1)
        self.adjustSize()

    def show_for(self, row: Row, chat: QWidget, palette: theme.Palette) -> None:
        self.fill(row.line.meta, palette)
        self.move(place_beside(chat.frameGeometry(), self.size(), _top_of(row), chat))
        self.show()


def _top_of(row: Row) -> int:
    target = row.bubble if row.bubble is not None else row
    return target.mapToGlobal(QPoint(0, 0)).y()


def place_beside(window, size: QSize, top: int, widget: QWidget | None = None) -> QPoint:
    """Where the details panel goes: just outside the chat window on whichever side
    has room (right first), level with the bubble, kept on the screen."""
    screen = widget.screen().availableGeometry() if widget is not None else None
    x = window.right() + Details.GAP
    if screen is not None and x + size.width() > screen.right():
        x = window.left() - Details.GAP - size.width()
    y = top
    if screen is not None:
        x = max(screen.left(), x)
        y = max(screen.top(), min(y, screen.bottom() - size.height()))
    return QPoint(x, y)


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
    ``shown`` carries what his face should show (the time, the weather);
    ``state`` carries what Kit is doing ("thinking", "speaking", "idle"...).
    ``settings_wanted`` asks the app to open Kit's window; ``resized`` reports the
    new size so it can be remembered."""

    replied = Signal(dict)
    shown = Signal(dict)  # something for his face to show (kit.shows)
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
        self._details: Details | None = None
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
        copy_all = QPushButton("Copy")
        copy_all.setObjectName("flat")
        copy_all.setToolTip("Copy the whole conversation (Ctrl+Shift+C), to paste anywhere")
        copy_all.clicked.connect(self.copy_conversation)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.copy_conversation)
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
        top.addWidget(copy_all)
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
        self.input.textChanged.connect(self._typing)
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
        self.state.emit("heard")  # a nod as it goes, then he thinks
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
                meta = m.get("meta")
                line = Line(role, m.get("text", ""), reply.get("detail", ""), tier=tier_of(meta))
                line.meta = details(meta, m.get("source"), m.get("at"))
                old.append(line)
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
            line.tier = tier_of(ev)
            line.meta = details(ev, ev.get("source"))
            if turn in self._current:
                index = self._current.pop(turn)
                self.lines[index] = line
                self.rows[index].update_line(line)
            else:
                self._add(line)
            self.replied.emit(reply)
        elif kind == "show":
            self.shown.emit(ev.get("show") or {})
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
        row.copied.connect(self.copy_text)
        row.copy_all.connect(self.copy_conversation)
        row.opened.connect(self.open_details)
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

    def open_details(self, row: Row) -> None:
        """Pop a reply's details (who answered, what it cost) out beside the chat."""
        if self._details is None:
            self._details = Details()
        self._details.show_for(row, self, self.palette)

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

    def _typing(self) -> None:
        """Kit listens while Dan types to him (his face leans in), unless he's busy
        answering; an emptied box lets him go back to what he was doing."""
        if self._in_flight:
            return
        typing = bool(self.input.toPlainText().strip())
        if typing and self.status.text() != "listening":
            self._set_state("listening")
        elif not typing and self.status.text() == "listening":
            self._set_state("idle")

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

    # Copying, for pasting Kit's words somewhere else

    def copy_conversation(self) -> None:
        self.copy_text(transcript(self.lines), "Copied the conversation")

    def copy_text(self, text: str, said: str = "Copied") -> None:
        QGuiApplication.clipboard().setText(text)
        self.status.setText(said)
        QTimer.singleShot(1800, self._restore_status)

    def _restore_status(self) -> None:
        if self.status.text().startswith("Copied"):
            self.status.setText("idle" if self._in_flight == 0 else "thinking")

    def text(self) -> str:
        """Everything shown, as plain text (for tests)."""
        parts = []
        for line in self.lines:
            parts.append(line.text)
            if line.detail:
                parts.append(line.detail)
        return "\n".join(parts)


def _start_rise(rise: QPropertyAnimation, bubble: QWidget) -> None:
    """Once the layout has placed the bubble, slide it up into that spot."""
    end = bubble.pos()
    rise.setStartValue(end + QPoint(0, 10))
    rise.setEndValue(end)
    rise.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
