"""Kit's window on the desk PC: Mood, Memory, Kit's settings, This PC, Look and Updates.

Mood shows how Kit is, like a Sims needs panel (kit.desk.mood); it only looks.

Memory and Kit's settings are the same as the brain's memory and settings pages
(they use the same API), so a change here shows there and the other way round.
This PC holds the desk app's own settings, Look changes how Kit and the chat
look (live, as you pick), and Updates keeps the app current from GitHub.

Calls to the brain and GitHub run on worker threads (``in_background``) and the
answers come back on the screen thread, so the window never freezes.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kit.desk import face3d, startup, theme
from kit.desk.client import BrainClient
from kit.desk.config import DeskConfig
from kit.desk.glow import FaceWidget
from kit.desk.mood import MoodPage
from kit.desk.update import PULL, VERSION, Release, Updater

# Tests flip this so background calls finish before the next line runs.
SYNC = False


class _Bridge(QObject):
    done = Signal(object, object)


_bridge: _Bridge | None = None


def in_background(work: Callable[[], object], then: Callable[[object], None]) -> None:
    """Run ``work`` off the screen thread and hand its result (or the exception it
    raised) to ``then`` back on the screen thread."""
    global _bridge
    if SYNC:
        try:
            result = work()
        except Exception as e:  # noqa: BLE001 (shown to Dan, never swallowed)
            result = e
        then(result)
        return
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(lambda callback, result: callback(result))
    bridge = _bridge

    def run() -> None:
        try:
            result = work()
        except Exception as e:  # noqa: BLE001
            result = e
        bridge.done.emit(then, result)

    threading.Thread(target=run, name="kit-window", daemon=True).start()


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(wrap)
    if name:
        label.setObjectName(name)
    return label


def _restyle(widget: QWidget, name: str) -> None:
    """Give a widget another style-sheet name (muted, error...) and redraw it."""
    widget.setObjectName(name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _button(text: str, slot: Callable, name: str = "") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.clicked.connect(slot)
    return b


def _page(title: str, intro: str) -> tuple[QWidget, QVBoxLayout]:
    """A scrolling page with a title and a line saying what it's for."""
    inner = QWidget()
    inner.setObjectName("scrollBody")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(10)
    layout.addWidget(_label(title, "title"))
    layout.addWidget(_label(intro, "muted"))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    return scroll, layout


def _list_text(text: str) -> list[str]:
    return [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]


# This PC: where the brain is, the token, what Kit may see.


class ConnectionForm(QWidget):
    """The desk app's own settings. Also the body of the first-run setup."""

    def __init__(self, config: DeskConfig, token: str, first_run: bool = False) -> None:
        super().__init__()
        self.config = config
        self.url = QLineEdit(config.brain_url)
        self.url.setPlaceholderText("http://kit-server:8600")
        self.token = QLineEdit(token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("run `kit token` on the server")
        self.result = _label("")
        test = _button("Test connection", self.test)
        self.watch = QCheckBox("Let Kit see which windows are open and what I'm working on")
        self.watch.setChecked(config.watch)
        self.show_face = QCheckBox("Show Kit's face on the desktop")
        self.show_face.setChecked(config.show_face)
        self.at_logon = QCheckBox("Start Kit when I log on")
        self.at_logon.setChecked(startup.enabled() or first_run)
        self.at_logon.setEnabled(sys.platform == "win32")
        self.hidden_apps = QLineEdit(", ".join(config.hidden_apps))
        self.hidden_words = QPlainTextEdit(", ".join(config.hidden_words))
        self.hidden_words.setFixedHeight(70)

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
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

    def test(self) -> None:
        client = BrainClient(self.url.text().strip(), self.token.text().strip())
        self.result.setText("Trying...")

        def done(status) -> None:
            client.close()
            if isinstance(status, Exception):
                self.result.setText(str(status))
                _restyle(self.result, "error")
            else:
                name, version = status.get("name", "Kit"), status.get("version")
                self.result.setText(f"Connected to {name} {version}.")
                _restyle(self.result, "muted")

        in_background(client.check, done)

    def values(self) -> tuple[DeskConfig, str, bool]:
        config = replace(
            self.config,
            brain_url=self.url.text().strip().rstrip("/") or self.config.brain_url,
            watch=self.watch.isChecked(),
            show_face=self.show_face.isChecked(),
            hidden_apps=_list_text(self.hidden_apps.text()),
            hidden_words=_list_text(self.hidden_words.toPlainText()),
        )
        return config, self.token.text().strip(), self.at_logon.isChecked()


class PcPage(QWidget):
    saved = Signal(object, str, bool)  # config, token, start at logon

    def __init__(self, config: DeskConfig, token: str) -> None:
        super().__init__()
        page, layout = _page(
            "This PC",
            "Where Kit's brain is, and what the desk app may tell him about this PC.",
        )
        self.form = ConnectionForm(config, token)
        layout.addWidget(self.form)
        row = QHBoxLayout()
        row.addStretch(1)
        self.note = _label("", "muted", wrap=False)
        row.addWidget(self.note)
        row.addWidget(_button("Save", self.save, "primary"))
        layout.addLayout(row)
        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

    def save(self) -> None:
        config, token, at_logon = self.form.values()
        self.form.config = config
        self.saved.emit(config, token, at_logon)
        self.note.setText("Saved.")


# Memory


class MemoryPage(QWidget):
    def __init__(self, client: Callable[[], BrainClient | None], brain_url: Callable[[], str]):
        super().__init__()
        self.client = client
        self.brain_url = brain_url
        self.facts_data: list[dict] = []
        page, layout = _page(
            "Memory",
            "What Kit knows about you. Search it the way he does, teach him something, "
            "pin what matters most, fix or forget anything.",
        )
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search memory the way Kit does")
        self.query.returnPressed.connect(self.search)
        row = QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(_button("Search", self.search))
        layout.addLayout(row)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setMaximumHeight(170)
        self.results.hide()
        layout.addWidget(self.results)

        self.teach = QLineEdit()
        self.teach.setPlaceholderText(
            "Teach Kit something, e.g. My tax returns are in Documents/Finance/Tax"
        )
        self.teach.returnPressed.connect(self.remember)
        row = QHBoxLayout()
        row.addWidget(self.teach, 1)
        row.addWidget(_button("Remember", self.remember, "primary"))
        layout.addLayout(row)
        self.note = _label("", "muted")
        layout.addWidget(self.note)

        self.count = _label("What he knows", "muted")
        layout.addWidget(self.count)
        self.facts = QListWidget()
        self.facts.setWordWrap(True)
        self.facts.setMinimumHeight(260)
        self.facts.itemDoubleClicked.connect(lambda _item: self.edit())
        layout.addWidget(self.facts, 1)
        row = QHBoxLayout()
        row.addWidget(_button("Pin or unpin", self.toggle_pin))
        row.addWidget(_button("Edit...", self.edit))
        row.addWidget(_button("Forget", self.forget))
        row.addStretch(1)
        row.addWidget(_button("Things and days in the browser", self.open_page, "flat"))
        layout.addLayout(row)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

    def _brain(self) -> BrainClient | None:
        client = self.client()
        if client is None:
            self.note.setText("Kit isn't set up yet: fill in This PC first.")
        return client

    def refresh(self) -> None:
        client = self._brain()
        if client is None:
            return
        in_background(client.facts, self._show_facts)

    def _show_facts(self, facts) -> None:
        if isinstance(facts, Exception):
            self.note.setText(str(facts))
            return
        self.facts_data = facts
        self.facts.clear()
        for f in facts:
            pin = "📌 " if f.get("pinned") else ""
            kind = f.get("kind") or "other"
            item = QListWidgetItem(f"{pin}{f.get('text', '')}   · {kind}")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self.facts.addItem(item)
        self.count.setText(f"What he knows ({len(facts)})" if facts else "Nothing yet.")

    def search(self) -> None:
        q = self.query.text().strip()
        client = self._brain()
        if not q or client is None:
            self.results.hide()
            return

        def show(found) -> None:
            self.results.clear()
            self.results.show()
            if isinstance(found, Exception):
                self.results.addItem(str(found))
                return
            hits = found.get("hits", [])
            if not hits:
                self.results.addItem("Nothing found.")
            for h in hits:
                where = h.get("source", "")
                title = f"{h['title']}: " if h.get("title") else ""
                self.results.addItem(f"[{where}] {title}{h.get('text', '')[:300]}")
            if found.get("words_only"):
                self.results.addItem("(Matching words only: Kit's meaning search is off.)")

        in_background(lambda: client.search(q), show)

    def remember(self) -> None:
        text = self.teach.text().strip()
        client = self._brain()
        if not text or client is None:
            return
        self.note.setText("Remembering...")

        def done(result) -> None:
            if isinstance(result, Exception):
                self.note.setText(str(result))
                return
            self.teach.clear()
            self.note.setText(
                {"same": "He already knew that.", "update": "Updated what he knew."}.get(
                    result.get("decision"), "Remembered."
                )
            )
            self.refresh()

        in_background(lambda: client.remember(text), done)

    def _selected(self) -> dict | None:
        item = self.facts.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _change(self, work: Callable[[], object]) -> None:
        def done(result) -> None:
            if isinstance(result, Exception):
                self.note.setText(str(result))
            self.refresh()

        in_background(work, done)

    def toggle_pin(self) -> None:
        fact, client = self._selected(), self._brain()
        if fact and client:
            self._change(lambda: client.edit_fact(fact["id"], pinned=not fact.get("pinned")))

    def edit(self) -> None:
        fact, client = self._selected(), self._brain()
        if not fact or client is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Edit", "What Kit knows:", fact["text"])
        if ok and text.strip() and text.strip() != fact["text"]:
            self._change(lambda: client.edit_fact(fact["id"], text=text.strip()))

    def forget(self) -> None:
        fact, client = self._selected(), self._brain()
        if not fact or client is None:
            return
        sure = QMessageBox.question(self, "Forget", f"Forget this?\n\n{fact['text']}")
        if sure == QMessageBox.StandardButton.Yes:
            self._change(lambda: client.forget(fact["id"]))

    def open_page(self) -> None:
        webbrowser.open(self.brain_url() + "/memory")


# Kit's settings, drawn from the brain's settings schema like the settings page.


def kind_of(prop: dict) -> str:
    if "enum" in prop:
        return "enum"
    if "anyOf" in prop:
        real = next((p for p in prop["anyOf"] if p.get("type") != "null"), {})
        return "optional-string" if real.get("type") == "string" else "json"
    if prop.get("type") == "array" and prop.get("items", {}).get("type") == "string":
        return "lines"
    extra = prop.get("additionalProperties")
    if prop.get("type") == "object" and isinstance(extra, dict) and extra.get("type") == "string":
        return "table"
    if prop.get("type") in ("string", "number", "integer", "boolean"):
        return prop["type"]
    return "json"


def make_control(kind: str, prop: dict, value) -> QWidget:
    if kind == "enum":
        box = QComboBox()
        box.addItems([str(v) for v in prop["enum"]])
        box.setCurrentText(str(value))
        return box
    if kind == "boolean":
        check = QCheckBox()
        check.setChecked(bool(value))
        return check
    if kind == "integer":
        spin = QSpinBox()
        spin.setRange(int(prop.get("minimum", -(10**9))), int(prop.get("maximum", 10**9)))
        spin.setValue(int(value or 0))
        return spin
    if kind == "number":
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(float(prop.get("minimum", -1e9)), float(prop.get("maximum", 1e9)))
        spin.setValue(float(value or 0))
        return spin
    if kind in ("lines", "table", "json"):
        box = QPlainTextEdit()
        if kind == "lines":
            box.setPlainText("\n".join(value or []))
        elif kind == "table":
            box.setPlainText("\n".join(f"{k} = {v}" for k, v in (value or {}).items()))
        else:
            box.setPlainText(json.dumps(value, indent=2))
        box.setFixedHeight(110 if kind == "json" else 80)
        return box
    text = "" if value is None else str(value)
    if len(text) > 70:
        box = QPlainTextEdit(text)
        box.setFixedHeight(80)
        return box
    return QLineEdit(text)


def read_control(kind: str, widget: QWidget):
    if kind == "enum":
        return widget.currentText()
    if kind == "boolean":
        return widget.isChecked()
    if kind in ("integer", "number"):
        return widget.value()
    text = widget.toPlainText() if isinstance(widget, QPlainTextEdit) else widget.text()
    if kind == "lines":
        return [s.strip() for s in text.splitlines() if s.strip()]
    if kind == "table":
        pairs = [s.split("=", 1) for s in text.splitlines() if "=" in s]
        return {k.strip(): v.strip() for k, v in pairs}
    if kind == "json":
        return json.loads(text)
    if kind == "optional-string":
        return text if text.strip() else None
    return text


class SettingsSection(QFrame):
    """One section of Kit's settings that folds away: click its name to open it."""

    def __init__(self, title: str, is_open: bool = False) -> None:
        super().__init__()
        self.setObjectName("section")
        self.title = title
        self.head = QToolButton()
        self.head.setObjectName("sectionHead")
        self.head.setText(title)
        self.head.setCheckable(True)
        self.head.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.head.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.toggled.connect(self._show_body)
        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(14, 0, 14, 12)
        self.words: list[tuple[str, list[int]]] = []  # each field's searchable text, rows
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.head)
        layout.addWidget(self.body)
        self.is_open = is_open
        self.head.setChecked(is_open)
        self._show_body(is_open)

    def add(self, key: str, control: QWidget, description: str = "") -> None:
        label = QLabel(key.replace("_", " "))
        label.setToolTip(description)
        control.setToolTip(description)
        rows = [self.form.rowCount()]
        self.form.addRow(label, control)
        if description:
            rows.append(self.form.rowCount())
            self.form.addRow("", _label(description, "help"))
        self.words.append((f"{key} {key.replace('_', ' ')} {description}".lower(), rows))

    def _show_body(self, on: bool) -> None:
        self.head.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)

    def search(self, words: list[str]) -> bool:
        """Show only the fields matching every word (all of them if the section's name
        matches), opened up; no words puts it back as Dan left it. Returns whether
        anything matched."""
        if not words:
            for _, rows in self.words:
                for row in rows:
                    self.form.setRowVisible(row, True)
            self.head.blockSignals(True)
            self.head.setChecked(self.is_open)
            self.head.blockSignals(False)
            self._show_body(self.is_open)
            self.show()
            return True
        whole = all(w in self.title.lower() for w in words)
        found = False
        for text, rows in self.words:
            hit = whole or all(w in text for w in words)
            found = found or hit
            for row in rows:
                self.form.setRowVisible(row, hit)
        self.setVisible(found)
        self.head.blockSignals(True)
        self.head.setChecked(found)
        self.head.blockSignals(False)
        self._show_body(found)
        return found


class BrainSettingsPage(QWidget):
    def __init__(self, client: Callable[[], BrainClient | None], brain_url: Callable[[], str]):
        super().__init__()
        self.client = client
        self.brain_url = brain_url
        self.schema: dict = {}
        self.fields: list[tuple[str, str | None, str, str, QWidget]] = []
        page, layout = _page(
            "Kit's settings",
            "How Kit's brain behaves: his models, voice, life and more. The same settings as "
            "the settings page in the browser; Kit uses a change from his next message.",
        )
        self.problem = _label("", "error")
        self.problem.hide()
        layout.addWidget(self.problem)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search settings (voice, cap, character...)")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self.search)
        layout.addWidget(self.find)
        self.nothing = _label("No setting matches that.", "muted")
        self.nothing.hide()
        layout.addWidget(self.nothing)
        self.groups: list[SettingsSection] = []
        self._opened: set[str] = set()  # sections Dan opened, kept across a reload
        self.sections = QVBoxLayout()
        self.sections.setSpacing(8)
        layout.addLayout(self.sections)
        layout.addStretch(1)
        row = QHBoxLayout()
        self.note = _label("", "muted")
        row.addWidget(self.note, 1)
        row.addWidget(_button("Open in the browser", self.open_page, "flat"))
        row.addWidget(_button("Undo last change", self.undo))
        row.addWidget(_button("Save", self.save, "primary"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(page, 1)
        bar = QFrame()
        bar.setObjectName("bar")
        bar.setLayout(row)
        row.setContentsMargins(24, 10, 24, 10)
        outer.addWidget(bar)

    def refresh(self) -> None:
        client = self.client()
        if client is None:
            self.note.setText("Kit isn't set up yet: fill in This PC first.")
            return
        self.note.setText("Loading...")
        in_background(lambda: (client.settings_schema(), client.settings()), self._loaded)

    def _loaded(self, result) -> None:
        if isinstance(result, Exception):
            self.note.setText(str(result))
            return
        self.schema, data = result
        self.render(data["settings"], data.get("problem"))
        self.note.setText("")

    def _resolve(self, node: dict) -> dict:
        ref = node.get("$ref") if isinstance(node, dict) else None
        return self.schema.get("$defs", {}).get(ref.split("/")[-1], {}) if ref else node

    def render(self, settings: dict, problem: str | None = None) -> None:
        self.problem.setText(problem or "")
        self.problem.setVisible(bool(problem))
        while self.sections.count():
            item = self.sections.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.fields = []
        self.groups = []
        for section, ref in self.schema.get("properties", {}).items():
            sec = self._resolve(ref)
            extra = sec.get("additionalProperties")
            if sec.get("type") == "object" and isinstance(extra, dict) and "$ref" in extra:
                entry = self._resolve(extra)
                for name, value in (settings.get(section) or {}).items():
                    self._group(f"{section}: {name}", section, name, entry, value)
                continue
            if sec.get("type") != "object" or not sec.get("properties"):
                continue
            self._group(section, section, None, sec, settings.get(section) or {})
        self.search(self.find.text())

    def _group(self, title: str, section: str, entry: str | None, sec: dict, values: dict):
        title = title.replace("_", " ")
        box = SettingsSection(title.capitalize(), title in self._opened)
        box.head.toggled.connect(lambda on, t=title, b=box: self._toggled(t, b, on))
        for key, raw in sec.get("properties", {}).items():
            prop = self._resolve(raw)
            kind = kind_of(prop)
            control = make_control(kind, prop, values.get(key))
            box.add(key, control, prop.get("description", ""))
            self.fields.append((section, entry, key, kind, control))
        self.groups.append(box)
        self.sections.addWidget(box)

    def _toggled(self, title: str, box: SettingsSection, on: bool) -> None:
        if self.find.text().strip():
            return  # opened by a search, not by Dan
        box.is_open = on
        (self._opened.add if on else self._opened.discard)(title)

    def search(self, text: str) -> None:
        """Narrow the sections to the settings matching what Dan typed."""
        words = text.lower().split()
        found = [box.search(words) for box in self.groups]
        self.nothing.setVisible(bool(words) and self.groups != [] and not any(found))

    def patch(self) -> dict:
        patch: dict = {}
        for section, entry, key, kind, control in self.fields:
            sec = patch.setdefault(section, {})
            target = sec.setdefault(entry, {}) if entry else sec
            target[key] = read_control(kind, control)
        return patch

    def save(self) -> None:
        client = self.client()
        if client is None:
            return
        try:
            patch = self.patch()
        except json.JSONDecodeError as e:
            self.note.setText(f"A box holds invalid JSON: {e}")
            return

        def done(result) -> None:
            if isinstance(result, Exception):
                self.note.setText(f"Not saved: {result}")
                return
            self.render(result["settings"], result.get("problem"))
            self.note.setText("Saved. Kit uses it from the next message.")

        in_background(lambda: client.save_settings(patch), done)

    def undo(self) -> None:
        client = self.client()
        if client is None:
            return

        def done(result) -> None:
            if isinstance(result, Exception):
                self.note.setText(str(result))
                return
            self.render(result["settings"], result.get("problem"))
            self.note.setText("Went back to the previous version.")

        in_background(client.undo_settings, done)

    def open_page(self) -> None:
        webbrowser.open(self.brain_url() + "/settings")


# Look


class Swatches(QWidget):
    """A row of round colour buttons plus Custom..."""

    picked = Signal(str)

    def __init__(self, colours: dict[str, str], current: str) -> None:
        super().__init__()
        self.current = current
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.buttons: dict[str, QPushButton] = {}
        for name, colour in colours.items():
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedSize(26, 26)
            b.clicked.connect(lambda _=False, c=colour: self.pick(c))
            self.buttons[colour] = b
            row.addWidget(b)
        row.addWidget(_button("Custom...", self.custom, "flat"))
        row.addStretch(1)
        self._paint()

    def custom(self) -> None:
        colour = QColorDialog.getColor(QColor(self.current), self, "Pick a colour")
        if colour.isValid():
            self.pick(colour.name())

    def pick(self, colour: str) -> None:
        self.current = colour
        self._paint()
        self.picked.emit(colour)

    def _paint(self) -> None:
        for colour, b in self.buttons.items():
            ring = "3px solid #888" if colour.lower() == self.current.lower() else "none"
            b.setStyleSheet(
                f"background: {colour}; border-radius: 13px; border: {ring}; padding: 0;"
            )


class LookPage(QWidget):
    """How Kit and the chat look. Which character he is lives in the brain (so it's the
    same everywhere); the rest is kept on this PC. The Glow-only choices hide while
    his character is 3D."""

    changed = Signal(object)  # the new DeskConfig
    character_picked = Signal(str)  # a character's id: Kit should become it

    def __init__(
        self, config: DeskConfig, client: Callable[[], BrainClient | None] | None = None
    ) -> None:
        super().__init__()
        self.config = config
        self.client = client or (lambda: None)
        page, layout = _page(
            "Look",
            "Make Kit yours. Changes show straight away; who he is goes everywhere he "
            "appears, the rest is kept on this PC.",
        )
        self.preview = FaceWidget()
        self.preview.setFixedSize(150, 150)
        self.preview.eye = QColor(config.eye_colour)
        top = QHBoxLayout()
        top.addWidget(self.preview)
        sample = QVBoxLayout()
        self.sample_kit = _label("G'day. This is how I'll look in the chat.")
        self.sample_you = _label("Looking good, Kit.")
        sample.addStretch(1)
        sample.addWidget(self.sample_kit)
        sample.addWidget(self.sample_you, 0, Qt.AlignmentFlag.AlignRight)
        sample.addStretch(1)
        top.addLayout(sample, 1)
        layout.addLayout(top)

        form = QFormLayout()
        self.form = form
        self.character = QComboBox()
        self.character.setToolTip("Which character Kit is, here, in home_app and on his robots")
        self.character.activated.connect(self._pick_character)
        form.addRow("Character", self.character)
        self.style_note = _label("", "help")
        form.addRow("", self.style_note)
        self.theme = QComboBox()
        self.theme.addItem("Match Windows", "system")
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(config.theme)))
        self.theme.currentIndexChanged.connect(self._changed)
        form.addRow("Theme", self.theme)
        self.accent = Swatches(theme.ACCENTS, config.accent)
        self.accent.picked.connect(self._changed)
        form.addRow("Accent colour", self.accent)
        self.eyes = Swatches(theme.EYES, config.eye_colour)
        self.eyes.picked.connect(self._changed)
        form.addRow("Kit's eyes", self.eyes)
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(80, 300)
        self.size.setValue(config.face_size)
        self.size.valueChanged.connect(self._changed)
        form.addRow("Face size", self.size)
        self.font_pt = QDoubleSpinBox()
        self.font_pt.setRange(8.0, 16.0)
        self.font_pt.setSingleStep(0.5)
        self.font_pt.setDecimals(1)
        self.font_pt.setSuffix(" pt")
        self.font_pt.setValue(config.font_pt)
        self.font_pt.valueChanged.connect(self._changed)
        form.addRow("Text size", self.font_pt)
        self.three_d = False
        self.show_style(False)
        self.speech = QCheckBox("Show what Kit says in a bubble under his face")
        self.speech.setChecked(config.speech_bubble)
        self.speech.toggled.connect(self._changed)
        form.addRow(self.speech)
        self.movement = QComboBox()
        for label, key in (
            ("Lively: hops, loops and big gestures", "lively"),
            ("Bouncy: even more", "bouncy"),
            ("A little: small gestures only", "a_little"),
            ("Still: hardly moves", "still"),
        ):
            self.movement.addItem(label, key)
        self.movement.setCurrentIndex(max(0, self.movement.findData(config.movement)))
        self.movement.currentIndexChanged.connect(self._changed)
        form.addRow("How much Kit moves", self.movement)
        self.boop = QCheckBox("Boop when Kit says something")
        self.boop.setToolTip("A little noise so you don't miss him. Turn it off once he talks.")
        self.boop.setChecked(config.boop)
        self.boop.toggled.connect(self._changed)
        form.addRow(self.boop)
        self.in_step = QCheckBox("Show Kit's words as he says them (when his voice is on)")
        self.in_step.setChecked(config.words_with_voice)
        self.in_step.toggled.connect(self._changed)
        form.addRow(self.in_step)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(_button("Back to Kit's own look", self.reset, "flat"))
        layout.addLayout(row)
        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)
        self._sample()

    def refresh(self) -> None:
        client = self.client()
        if client is None:
            return
        in_background(client.face_presets, self._presets)

    def _presets(self, result) -> None:
        if isinstance(result, Exception):
            return  # an older brain: the character is still on Kit's settings page
        self.character.blockSignals(True)
        self.character.clear()
        for preset in result.get("presets", []):
            self.character.addItem(preset.get("name") or preset["id"], preset["id"])
        self.character.setCurrentIndex(max(0, self.character.findData(result.get("current"))))
        self.character.blockSignals(False)

    def _pick_character(self, index: int) -> None:
        picked = self.character.itemData(index)
        if picked:
            self.character_picked.emit(picked)

    def show_style(self, three_d: bool) -> None:
        """Show the choices that fit his character: eye colours are for the Glow face."""
        self.three_d = three_d
        self.form.setRowVisible(self.eyes, not three_d)
        self.style_note.setText(
            "His 3D face brings its own colours, so there's no eye colour to pick."
            if three_d
            else "The Glow face: pick his eye colour below."
        )

    def values(self) -> DeskConfig:
        return replace(
            self.config,
            theme=self.theme.currentData(),
            accent=self.accent.current,
            eye_colour=self.eyes.current,
            face_size=self.size.value(),
            font_pt=self.font_pt.value(),
            speech_bubble=self.speech.isChecked(),
            boop=self.boop.isChecked(),
            movement=self.movement.currentData(),
            words_with_voice=self.in_step.isChecked(),
        )

    def _changed(self, *_args) -> None:
        self.config = self.values()
        self.preview.eye = QColor(self.config.eye_colour)
        self._sample()
        self.changed.emit(self.config)

    def _sample(self) -> None:
        p = theme.palette(self.config.theme, self.config.accent)
        size = f"font-size: {self.config.font_pt}pt;"
        self.sample_kit.setStyleSheet(
            f"background: {p.bubble}; color: {p.text}; border: 1px solid {p.line};"
            f" border-radius: 16px; padding: 8px 12px; {size}"
        )
        self.sample_you.setStyleSheet(
            f"background: {p.accent}; color: {p.accent_text}; border-radius: 16px;"
            f" padding: 8px 12px; {size}"
        )

    def reset(self) -> None:
        d = DeskConfig()
        self.theme.setCurrentIndex(self.theme.findData(d.theme))
        self.accent.pick(d.accent)
        self.eyes.pick(d.eye_colour)
        self.size.setValue(d.face_size)
        self.font_pt.setValue(d.font_pt)
        self.speech.setChecked(d.speech_bubble)
        self.boop.setChecked(d.boop)
        self.movement.setCurrentIndex(self.movement.findData(d.movement))
        self.in_step.setChecked(d.words_with_voice)

    def show_boop(self, on: bool) -> None:
        """The tray's boop switch changed: show it here without saving again."""
        self.boop.blockSignals(True)
        self.boop.setChecked(on)
        self.boop.blockSignals(False)
        self.config = replace(self.config, boop=on)


# Updates


class UpdatesPage(QWidget):
    settings_changed = Signal(object, str)  # DeskConfig, GitHub token
    install = Signal(object)  # the downloaded installer's Path

    def __init__(
        self,
        config: DeskConfig,
        token: str,
        download_dir: Path,
        updater: Callable[[DeskConfig, str], Updater] = lambda c, t: Updater(c.update_repo, t),
    ) -> None:
        super().__init__()
        self.config = config
        self.download_dir = download_dir
        self.make_updater = updater
        self.release: Release | None = None
        page, layout = _page(
            "Updates",
            "New versions of the desk app are published on GitHub. Kit checks once a day "
            "and asks before installing anything.",
        )
        test = f", a test build from pull request #{PULL}" if PULL else ""
        self.current = _label(f"This is Kit desk app {VERSION}{test}.")
        layout.addWidget(self.current)
        self.auto = QCheckBox("Check for updates once a day")
        self.auto.setChecked(config.check_updates)
        self.auto.toggled.connect(self._settings)
        self.token = QLineEdit(token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("github_pat_...")
        self.token.editingFinished.connect(self._settings)
        self.repo = QLineEdit(config.update_repo)
        self.repo.editingFinished.connect(self._settings)
        form = QFormLayout()
        form.addRow(self.auto)
        form.addRow("GitHub token", self.token)
        form.addRow(
            "",
            _label(
                "Kit's repo is private, so GitHub needs a token to show the releases. Make "
                "one at github.com > Settings > Developer settings > Fine-grained tokens: "
                "only the Kit repository, Contents: Read-only. It's kept in this PC's Kit "
                "Desk folder.",
                "help",
            ),
        )
        form.addRow("Repository", self.repo)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.check_button = _button("Check now", self.check)
        self.install_button = _button("Download and install", self.download, "primary")
        self.install_button.hide()
        row.addWidget(self.check_button)
        row.addWidget(self.install_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = _label("", "muted")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.notes = _label("")
        self.notes.setTextFormat(Qt.TextFormat.MarkdownText)
        self.notes.setOpenExternalLinks(True)
        layout.addWidget(self.notes)
        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

    def _settings(self, *_args) -> None:
        self.config = replace(
            self.config,
            check_updates=self.auto.isChecked(),
            update_repo=self.repo.text().strip() or DeskConfig().update_repo,
        )
        self.settings_changed.emit(self.config, self.token.text().strip())

    def check(self) -> None:
        self.status.setText("Asking GitHub...")
        self.check_button.setEnabled(False)
        updater = self.make_updater(self.config, self.token.text().strip())

        def done(result) -> None:
            updater.close()
            self.check_button.setEnabled(True)
            self.show_release(result)

        in_background(updater.newer, done)

    def show_release(self, result) -> None:
        """Show what a check found: a newer release, nothing newer, or a problem."""
        if isinstance(result, Exception):
            self.status.setText(str(result))
            return
        self.release = result
        if result is None:
            self.status.setText(f"You're up to date ({VERSION}).")
            self.install_button.hide()
            self.notes.setText("")
            return
        if result.has_this_build:
            size = result.size // 1_000_000
            self.status.setText(f"Version {result.version} is ready ({size} MB).")
            self.install_button.setText("Download and install")
        else:  # main's newer release, still without what this test build is trying out
            self.status.setText(
                f"Version {result.version} is out, but it was built without this test "
                "build's changes. Kit will offer it once they're merged."
            )
            self.install_button.setText("Install it anyway")
        self.notes.setText(result.notes[:3000] or f"[See it on GitHub]({result.page})")
        self.install_button.show()

    def download(self) -> None:
        release = self.release
        if release is None:
            return
        self.install_button.setEnabled(False)
        self.progress.setRange(0, max(1, release.size))
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("Downloading...")
        updater = self.make_updater(self.config, self.token.text().strip())
        bridge = _Progress()
        bridge.moved.connect(self.progress.setValue)

        def work() -> Path:
            return updater.download(
                release, self.download_dir, lambda got, _total: bridge.moved.emit(got)
            )

        def done(result) -> None:
            updater.close()
            self.install_button.setEnabled(True)
            if isinstance(result, Exception):
                self.progress.hide()
                self.status.setText(str(result))
                return
            self.status.setText("Installing. Kit will close and come back in a moment.")
            self.install.emit(result)

        in_background(work, done)


class _Progress(QObject):
    moved = Signal(int)


# The window


class KitWindow(QWidget):
    """Kit's window, opened from the tray menu or the ⚙ in the chat."""

    PAGES = ["Mood", "Memory", "Kit's settings", "This PC", "Look", "Updates"]

    def __init__(
        self,
        config: DeskConfig,
        token: str,
        update_token: str,
        client: Callable[[], BrainClient | None],
        brain_url: Callable[[], str],
        download_dir: Path,
        updater: Callable[[DeskConfig, str], Updater] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Kit")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(900, 660)
        self.setMinimumSize(620, 460)
        self.mood = MoodPage(client, in_background)
        self.memory = MemoryPage(client, brain_url)
        self.brain_settings = BrainSettingsPage(client, brain_url)
        self.pc = PcPage(config, token)
        self.client = client
        self.look = LookPage(config, client)
        self.look.character_picked.connect(self._pick_character)
        self._look: tuple[str | None, dict] = (None, {})
        self._faces3d: list[face3d.Face3D | None] = [None, None]
        kwargs = {"updater": updater} if updater else {}
        self.updates = UpdatesPage(config, update_token, download_dir, **kwargs)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(180)
        self.nav.addItems(self.PAGES)
        self.stack = QStackedWidget()
        for page in (self.mood, self.memory, self.brain_settings, self.pc, self.look, self.updates):
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._go)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.nav.setCurrentRow(0)

    def show_page(self, name: str) -> None:
        self.nav.setCurrentRow(self.PAGES.index(name))
        self.show()
        self.raise_()
        self.activateWindow()

    def _go(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    character_changed = Signal()  # Kit became another character from the Look page

    def _pick_character(self, name: str) -> None:
        client = self.client()
        if client is None:
            return

        def done(result) -> None:
            if isinstance(result, Exception):
                self.look.style_note.setText(f"Couldn't change him: {result}")
                return
            self.character_changed.emit()

        in_background(lambda: client.save_settings({"face": {"character": name}}), done)

    def use_look(self, brain_url: str | None, look: dict) -> None:
        """Draw Kit on the Mood and Look pages as he looks on the desk: Glow, or his
        3D face while this window is open (each 3D face is a web page, so they're
        only kept while they can be seen)."""
        self._look = (brain_url, look)
        self.look.show_style(face3d.wants_3d(look))
        shown = brain_url if self.isVisible() else None
        for i, widget in enumerate((self.mood.face, self.look.preview)):
            self._faces3d[i] = face3d.sync(widget, shown, look, self._faces3d[i])

    def showEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        self.use_look(*self._look)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().hideEvent(event)
        self.use_look(*self._look)

    def apply_look(self, palette: theme.Palette, font_pt: float) -> None:
        self.setStyleSheet(theme.window_style(palette, font_pt))
        self.mood.apply_look(palette)
