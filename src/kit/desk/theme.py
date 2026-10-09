"""How the desk app looks: light or dark, the accent colour, text size and Glow's
eye colour. Dan picks these on the Look page; everything else asks this module
for its colours and style sheets, so a change shows everywhere at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

ACCENTS = {
    "Blue": "#3b78d8",
    "Teal": "#14a39a",
    "Green": "#2f9e44",
    "Purple": "#7c5cd6",
    "Orange": "#e8590c",
    "Pink": "#d6336c",
}
EYES = {
    "Glow": "#7ef3e6",
    "Sky": "#7cc4ff",
    "Mint": "#8ef5a4",
    "Amber": "#ffc66b",
    "Rose": "#ff9ec0",
    "Violet": "#c4a6ff",
}


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str  # window background
    panel: str  # header and input bar
    bubble: str  # Kit's bubbles (the chat model: local or cloud)
    work: str  # bubbles answered by the work model, and their edge
    work_line: str
    expert: str  # bubbles answered by the expert model, and their edge
    expert_line: str
    text: str
    muted: str
    line: str
    accent: str
    accent_text: str
    error: str
    code: str  # code block background


def is_dark(theme: str) -> bool:
    if theme == "dark":
        return True
    if theme == "light":
        return False
    app = QGuiApplication.instance()
    if app is None:
        return True
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt older than 6.5
        return True


def palette(theme: str = "system", accent: str = ACCENTS["Blue"]) -> Palette:
    if not QColor(accent).isValid():
        accent = ACCENTS["Blue"]
    if is_dark(theme):
        return Palette(
            True,
            bg="#141517",
            panel="#1c1d20",
            bubble="#25272b",
            work="#3a2816",
            work_line="#a8642a",
            expert="#1b3222",
            expert_line="#3f8f55",
            text="#ecebe7",
            muted="#9c9a94",
            line="#34363b",
            accent=accent,
            accent_text="#ffffff",
            error="#f2b8b5",
            code="#101113",
        )
    return Palette(
        False,
        bg="#f6f5f2",
        panel="#ffffff",
        bubble="#ffffff",
        work="#fdebd6",
        work_line="#eba25c",
        expert="#e1f3e4",
        expert_line="#76c08a",
        text="#1d1d1b",
        muted="#6b6a66",
        line="#e2e0da",
        accent=accent,
        accent_text="#ffffff",
        error="#b3261e",
        code="#f0efeb",
    )


def window_style(p: Palette, font_pt: float = 10.5) -> str:
    """The style sheet shared by the chat and Kit's window."""
    hover = QColor(p.accent).lighter(115).name()
    return f"""
    QWidget {{ font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Inter', sans-serif;
               font-size: {font_pt}pt; color: {p.text}; }}
    QWidget#root, QScrollArea, QWidget#scrollBody, QStackedWidget {{ background: {p.bg}; }}
    QScrollArea {{ border: none; }}
    QFrame#bar {{ background: {p.panel}; border: none; }}
    QFrame#barLine {{ background: {p.line}; max-height: 1px; min-height: 1px; border: none; }}
    QLabel#muted, QLabel#status {{ color: {p.muted}; }}
    QLabel#title {{ font-size: {font_pt + 3}pt; font-weight: 600; }}
    QLabel#help {{ color: {p.muted}; font-size: {font_pt - 1}pt; }}
    QLabel#error {{ color: {p.error}; }}
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {p.bg}; color: {p.text}; border: 1px solid {p.line};
        border-radius: 12px; padding: 6px 10px; selection-background-color: {p.accent}; }}
    QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {p.accent}; }}
    QPlainTextEdit#input {{ border-radius: 18px; padding: 8px 14px; background: {p.bg}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {p.panel}; color: {p.text};
        selection-background-color: {p.accent}; border: 1px solid {p.line}; }}
    QPushButton {{ background: {p.bubble}; color: {p.text}; border: 1px solid {p.line};
        border-radius: 12px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:disabled {{ color: {p.muted}; }}
    QPushButton#primary, QPushButton#send {{ background: {p.accent}; color: {p.accent_text};
        border: none; }}
    QPushButton#primary:hover, QPushButton#send:hover {{ background: {hover}; }}
    QPushButton#send {{ border-radius: 18px; min-width: 36px; max-width: 36px;
        min-height: 36px; max-height: 36px; padding: 0; font-size: {font_pt + 3}pt; }}
    QPushButton#flat {{ background: transparent; border: none; color: {p.muted};
        padding: 4px 8px; border-radius: 10px; }}
    QPushButton#flat:hover {{ background: {p.bubble}; color: {p.text}; }}
    QPushButton#jump {{ background: {p.panel}; color: {p.text}; border: 1px solid {p.line};
        border-radius: 14px; padding: 4px 12px; }}
    QListWidget {{ background: {p.panel}; border: 1px solid {p.line}; border-radius: 12px;
        padding: 6px; outline: none; }}
    QListWidget::item {{ padding: 7px 8px; border-radius: 8px; }}
    QListWidget::item:selected {{ background: {p.bubble}; color: {p.text};
        border: 1px solid {p.accent}; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
    QListWidget#nav {{ background: {p.panel}; border: none; outline: none; padding: 8px; }}
    QListWidget#nav::item {{ padding: 9px 12px; border-radius: 10px; color: {p.text}; }}
    QListWidget#nav::item:selected {{ background: {p.bubble}; color: {p.text};
        border: none; border-left: 3px solid {p.accent}; }}
    QListWidget#nav::item:hover {{ background: {p.bubble}; }}
    QGroupBox {{ border: 1px solid {p.line}; border-radius: 14px; margin-top: 16px;
        padding: 14px 12px 10px 12px; background: {p.panel}; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 4px;
        color: {p.muted}; }}
    QFrame#section {{ border: 1px solid {p.line}; border-radius: 14px; background: {p.panel}; }}
    QToolButton#sectionHead {{ border: none; background: transparent; color: {p.text};
        font-weight: 600; padding: 10px 12px; text-align: left; }}
    QToolButton#sectionHead:hover {{ color: {p.accent}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {p.line}; background: {p.bg}; }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.line}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; }}
    QToolTip {{ background: {p.panel}; color: {p.text}; border: 1px solid {p.line}; }}
    """


TIERS = ("chat", "work", "expert")  # which model answered: kit.brain's roles


def bubble_style(p: Palette, role: str, tier: str = "chat") -> str:
    """Rounded bubbles: Dan's in the accent colour on the right, Kit's on the left,
    coloured by who answered: plain for the chat model, orange for the work model,
    green for the expert."""
    if role == "you":
        bg, fg, border = p.accent, p.accent_text, p.accent
        corners = "border-bottom-right-radius: 6px;"
    else:
        bg, border = {
            "work": (p.work, p.work_line),
            "expert": (p.expert, p.expert_line),
        }.get(tier, (p.bubble, p.line))
        fg = p.text
        corners = "border-bottom-left-radius: 6px;"
    return (
        f"QFrame#bubble {{ background: {bg}; border: 1px solid {border};"
        f" border-radius: 18px; {corners} }}"
        f" QLabel {{ color: {fg}; background: transparent; border: none; }}"
    )


def details_style(p: Palette) -> str:
    """The panel that pops out beside the chat with a reply's details."""
    return (
        f"QFrame#details {{ background: {p.panel}; border: 1px solid {p.line};"
        f" border-radius: 12px; }}"
        f" QLabel {{ color: {p.text}; background: transparent; border: none; }}"
        f" QLabel#muted {{ color: {p.muted}; }}"
        f" QLabel#title {{ font-weight: 600; }}"
    )
