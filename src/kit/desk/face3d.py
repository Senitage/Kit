"""Kit's 3D face on the desk: the brain's face page laid over the Glow face.

When Kit's character has a 3D look for the desk (``use.desk`` is a ``model``
look), the desk app doesn't draw him itself. It opens the brain's face page
(``/face/``, kit.face.serve) in a see-through web view that fills his window and
tells it what the face is doing: the same ``Face`` the Glow painter reads keeps
running underneath (emotion, state, gestures, where he looks), and ``Mirror``
copies each change across as a call to the page's ``kit`` API. The page, the 3D
engine, the model and its pack all come from the brain and reload themselves when
the brain has new ones, so a new face needs no new desk app.

Clicks, drags and the menu still go to the Glow window underneath. If Qt's web
engine is missing or the page can't load, Glow stays.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlencode

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtWidgets import QWidget

from kit.face import Face

log = logging.getLogger(__name__)

APP = "desk"
STEP_MS = 50  # how often face changes are copied to the page


def available() -> bool:
    """Whether this desk app can show web pages (Qt's web engine is installed)."""
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return False
    return True


def prepare() -> None:
    """Get Qt's web engine ready; call before the QApplication is made."""
    if available():
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


def page_url(brain_url: str) -> str:
    """The brain's face page for the desk. No character: the page draws the one the
    brain is set to, so switching ``face.character`` reloads it."""
    return f"{brain_url.rstrip('/')}/face/?{urlencode({'app': APP})}"


def _call(name: str, *args) -> str:
    return f"kit.{name}({', '.join(json.dumps(a) for a in args)});"


class Mirror:
    """Turns what a ``Face`` is doing into calls to the face page, sending only what
    changed since last time. ``reset`` makes the next ``calls`` send everything."""

    def __init__(self, face: Face) -> None:
        self.face = face
        self.reset()

    def reset(self) -> None:
        self._emotion: str | None = None
        self._state: str | None = None
        self._clip = self.face.clip  # a gesture already playing stays put
        self._look: tuple | None = None

    def calls(self) -> list[str]:
        f = self.face
        out = []
        if f.emotion != self._emotion:
            self._emotion = f.emotion
            out.append(_call("setEmotion", f.emotion))
        if f.state != self._state:
            self._state = f.state
            out.append(_call("setState", f.state))
        clip = f.clip
        if clip is not None and clip != self._clip:
            out.append(_call("play", clip[0]))
        self._clip = clip
        look = f.looking
        if look is not None and look != self._look:
            self._look = look
            out.append(_call("lookAt", round(look[0], 3), round(look[1], 3)))
        return out


class _NoPaint(QObject):
    """Stops the Glow window painting while the 3D page covers it."""

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt's name)
        return event.type() == QEvent.Type.Paint


class Face3D:
    """The face page laid over a Glow ``FaceWidget``. ``detach`` puts Glow back."""

    def __init__(self, widget: QWidget, brain_url: str) -> None:
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.widget = widget
        self.url = page_url(brain_url)
        self.mirror = Mirror(widget.face)
        self.view = QWebEngineView(widget)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.view.loadFinished.connect(self._loaded)
        self.view.setGeometry(widget.rect())
        self._no_paint = _NoPaint(widget)
        self._resize = _Resize(self)
        widget.installEventFilter(self._resize)
        self._play_show = widget.__dict__.get("play_show")
        if hasattr(widget, "play_show"):
            widget.play_show = self.show  # the brain's shows play on the 3D face
        self._timer = QTimer(widget)
        self._timer.timeout.connect(self._step)
        self._ready = False
        self.view.load(QUrl(self.url))
        self.view.show()

    def _loaded(self, ok: bool) -> None:
        self._ready = ok
        if not ok:
            log.warning("couldn't load Kit's 3D face from %s; showing Glow", self.url)
            self.widget.removeEventFilter(self._no_paint)
            self.view.hide()
            return
        # the page's input widget only exists once it's loaded
        proxy = self.view.focusProxy()
        if proxy is not None:
            proxy.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.widget.installEventFilter(self._no_paint)
        self.view.show()
        self.mirror.reset()  # a reload starts the page afresh
        self._step()
        self._timer.start(STEP_MS)
        self.widget.update()

    def _step(self) -> None:
        if not self._ready:
            return
        calls = self.mirror.calls()
        if calls:
            self.run("".join(calls))

    def run(self, js: str) -> None:
        self.view.page().runJavaScript(f"window.kit && (function(){{{js}}})();")

    def show(self, what: dict) -> bool:
        """A show from the brain (the time, the weather), played by the 3D face."""
        if self._ready:
            self.run(_call("show", what))
        return True

    def fit(self) -> None:
        self.view.setGeometry(self.widget.rect())

    def detach(self) -> None:
        self._timer.stop()
        self.widget.removeEventFilter(self._no_paint)
        self.widget.removeEventFilter(self._resize)
        if self._play_show is not None:
            self.widget.play_show = self._play_show
        elif "play_show" in self.widget.__dict__:
            del self.widget.play_show
        self.view.setParent(None)
        self.view.deleteLater()
        self.widget.update()


class _Resize(QObject):
    def __init__(self, face3d: Face3D) -> None:
        super().__init__(face3d.widget)
        self.face3d = face3d

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt's name)
        if event.type() == QEvent.Type.Resize:
            self.face3d.fit()
        return False


def wants_3d(look: dict) -> bool:
    """Whether a look (the character's desk look) is drawn by the face page."""
    return look.get("style") == "model"


def sync(widget: QWidget, brain_url: str | None, look: dict, current: Face3D | None):
    """Attach, keep or detach the 3D face so it matches ``look`` (the desk look of
    the character in use) and the brain at ``brain_url``. Returns what's attached."""
    want = bool(brain_url) and wants_3d(look) and available()
    if current is not None and (not want or current.url != page_url(brain_url or "")):
        current.detach()
        current = None
    if want and current is None:
        try:
            current = Face3D(widget, brain_url)
        except Exception:  # a broken web engine mustn't take Glow with it
            log.exception("couldn't start Kit's 3D face; showing Glow")
            current = None
    return current
