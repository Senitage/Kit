"""Kit's 3D face on the desk: the brain's face page laid over the Glow face.

When Kit's character has a 3D look for the desk (``use.desk`` is a ``model``
look), the desk app doesn't draw him itself. It opens the brain's face page
(``/face/``, kit.face.serve) in a see-through web view that fills his window and
tells it what the face is doing: the same ``Face`` the Glow painter reads keeps
running underneath (emotion, state, gestures, where he looks), and ``Mirror``
copies each change across as a call to the page's ``kit`` API. The page, the 3D
engine, the model and its pack all come from the brain and reload themselves when
the brain has new ones, so a new face needs no new desk app.

The web view itself is never on screen. It renders off screen and each frame is
copied into the Glow window, which paints it in place of Glow. A web view laid
inside a see-through window flickers on Windows (the window and the page's GPU
surface are composited separately), so this keeps the desktop window an ordinary
painted one. Clicks, drags and the menu still go to that window. If Qt's web
engine is missing or the page can't load, Glow stays.

The page hands its frames (and whether Kit's model is drawn) back over a web
channel, to ``_Bridge``. Asking with ``runJavaScript`` and a result callback looked
simpler, but PySide never frees a string handed back that way: at 60 frames a
second that leaked about 110 MB a minute until Windows ran out of memory.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from urllib.parse import urlencode

from PySide6.QtCore import QEvent, QFile, QIODevice, QObject, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from kit.face import Face

log = logging.getLogger(__name__)

APP = "desk"
STEP_MS = 16  # how often face changes (and where the mouse is) are copied to the page
FRAME_MS = 16  # how often the page's picture is copied to the window (up to 60 fps)
BRIDGE = "kitDesk"  # the desk's object on the page's web channel
# both answer through the bridge, never as runJavaScript results (see above)
FRAME_JS = f"window.{BRIDGE} && {BRIDGE}.frame(window.kit && kit.frame ? kit.frame() || '' : '')"
DRAWN_JS = f"window.{BRIDGE} && {BRIDGE}.drawn(!!(window.kit && window.kit.ready))"
ASK_AGAIN_S = 1.0  # a frame asked for that never came back (a reload) is asked again
PNG_PREFIX = "data:image/png;base64,"


def available() -> bool:
    """Whether this desk app can show web pages (Qt's web engine is installed)."""
    try:
        from PySide6 import QtWebChannel, QtWebEngineWidgets  # noqa: F401
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
        self._dials: tuple | None = None
        self._talk: float | None = None

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
        dials = (round(f.arousal, 2), round(f.valence, 2))
        if dials != self._dials:
            self._dials = dials
            out.append(_call("setDials", *dials))
        talk = None if f.talk_level is None else round(f.talk_level, 2)
        if talk != self._talk:
            self._talk = talk
            out.append(_call("setTalk", talk))
        return out


def _blank(frame: QPixmap) -> bool:
    """Whether a frame has nothing in it: Kit sits in the middle, so a frame with
    nothing drawn across its middle is empty."""
    if frame.isNull() or frame.width() < 4 or frame.height() < 4:
        return True
    img = frame.toImage()
    w, h = img.width(), img.height()
    y = h // 2
    return all(img.pixelColor(w * i // 8, y).alpha() == 0 for i in range(2, 7))


class _Paint(QObject):
    """Paints the 3D page's latest frame in the Glow window instead of Glow."""

    def __init__(self, face3d: Face3D) -> None:
        super().__init__(face3d.widget)
        self.face3d = face3d

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt's name)
        if event.type() != QEvent.Type.Paint:
            return False
        frame = self.face3d.frame
        if frame is not None and not frame.isNull():
            p = QPainter(watched)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(watched.rect(), frame)
            p.end()
        return True


class Face3D:
    """The face page drawn in a Glow ``FaceWidget``. ``detach`` puts Glow back.

    Glow keeps drawing until the page says Kit's model is on screen, and again
    whenever the page is loading or can't reach the brain, so he never blinks out.
    While the 3D face is shown, Glow's own 60 fps timer stops and the window paints
    the page's frames instead. The face's rig still ticks here, so moods, gestures
    and gaze carry on."""

    def __init__(self, widget: QWidget, brain_url: str) -> None:
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.widget = widget
        self.url = page_url(brain_url)
        self.mirror = Mirror(widget.face)
        # off screen: rendered and copied, never composited over the window
        self.view = QWebEngineView()
        self.view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self._bridge = _Bridge(self)
        _connect(self.view.page(), self._bridge)
        self.view.loadStarted.connect(self._loading)
        self.view.loadFinished.connect(self._loaded)
        self.view.resize(widget.size())
        self.frame: QPixmap | None = None  # the page's latest picture
        self._paint = _Paint(self)
        self._resize = _Resize(self)
        widget.installEventFilter(self._resize)
        self._play_show = widget.__dict__.get("play_show")
        if hasattr(widget, "play_show"):
            widget.play_show = self.show  # the brain's shows play on the 3D face
        self._timer = QTimer(widget)
        self._timer.timeout.connect(self._step)
        self._frames = QTimer(widget)
        self._frames.timeout.connect(self._grab)
        self._ready = False  # the page has loaded
        self.covering = False  # Kit's model is drawn, so Glow is stopped
        self._steps = 0
        self.loads = 0  # page loads, for the log: a page reloading over and over shows here
        self.grabs = self.blanks = 0  # frames copied, and how many came back empty
        self._asking = False  # a frame has been asked for and not come back yet
        self._asked = 0.0  # when
        self._told = time.monotonic()
        self.view.load(QUrl(self.url))
        self.view.show()
        self._timer.start(STEP_MS)

    def _loading(self) -> None:
        self._ready = False
        self._cover(False)

    def _loaded(self, ok: bool) -> None:
        self.loads += 1
        if not ok:
            log.warning("couldn't load Kit's 3D face from %s; showing Glow", self.url)
            return
        if self.loads > 1:
            log.info("Kit's 3D face reloaded (%d loads)", self.loads)
        self._ready = True
        self.mirror.reset()  # a reload starts the page afresh

    def _cover(self, on: bool) -> None:
        """Hand the window to the 3D face (stop Glow) or back to Glow."""
        if on == self.covering:
            return
        self.covering = on
        log.info("Kit's 3D face %s", "shown" if on else "hidden; showing Glow")
        glow_timer = getattr(self.widget, "_timer", None)
        if on:
            self._asking = False
            self._grab()
            self.widget.installEventFilter(self._paint)
            self._frames.start(FRAME_MS)
            if glow_timer is not None:
                glow_timer.stop()
        else:
            self._frames.stop()
            self.widget.removeEventFilter(self._paint)
            self.frame = None
            if glow_timer is not None:
                glow_timer.start(16)
        self.widget.update()

    def _grab(self) -> None:
        """Ask the page for its picture; ``_take`` paints it when it comes back. The
        page draws and reads the picture in one go, so it is never half drawn or
        empty, which copying the off-screen view itself can be on Windows."""
        now = time.monotonic()
        if self._asking and now - self._asked < ASK_AGAIN_S:
            return
        self._asking, self._asked = True, now
        self.view.page().runJavaScript(FRAME_JS)

    def _take(self, data: str) -> None:
        """A frame from the page: a PNG data URL, or empty (no ``kit.frame`` yet)."""
        self._asking = False
        if not self.covering:
            return
        frame = None
        if data.startswith(PNG_PREFIX):
            frame = QPixmap()
            frame.loadFromData(base64.b64decode(data[len(PNG_PREFIX) :]), "PNG")
        elif not data:
            frame = self.view.grab()  # a brain without kit.frame yet
        self.grabs += 1
        if frame is None or _blank(frame):
            self.blanks += 1
        else:
            self.frame = frame
            self.widget.update()
        now = time.monotonic()
        if self.blanks and now - self._told > 60:
            log.info("Kit's 3D face: %d of %d frames came back empty", self.blanks, self.grabs)
            self._told, self.blanks, self.grabs = now, 0, 0

    def _drawn(self, drawn) -> None:
        self._cover(bool(drawn) and self._ready)

    def _step(self) -> None:
        if self.covering:  # Glow's timer is stopped: the rig still ticks
            self.widget.tick_face(time.monotonic())
        if not self._ready:
            return
        calls = self.mirror.calls()
        if calls:
            self.run("".join(calls))
        self._steps += 1
        if self._steps % 30 == 1:  # twice a second: is Kit's model on screen?
            self.view.page().runJavaScript(DRAWN_JS)

    def run(self, js: str) -> None:
        self.view.page().runJavaScript(f"window.kit && (function(){{{js}}})();")

    def show(self, what: dict) -> bool:
        """A show from the brain (the time, the weather), played by the 3D face."""
        if self._ready:
            self.run(_call("show", what))
        return True

    def fit(self) -> None:
        self.view.resize(self.widget.size())

    def detach(self) -> None:
        self._timer.stop()
        self._cover(False)
        self.widget.removeEventFilter(self._resize)
        if self._play_show is not None:
            self.widget.play_show = self._play_show
        elif "play_show" in self.widget.__dict__:
            del self.widget.play_show
        self.view.deleteLater()
        self.widget.update()


class _Bridge(QObject):
    """The desk's end of the page's web channel: the page calls these."""

    def __init__(self, face3d: Face3D) -> None:
        super().__init__(face3d.widget)
        self.face3d = face3d

    @Slot(str)
    def frame(self, data: str) -> None:
        self.face3d._take(data)

    @Slot(bool)
    def drawn(self, drawn: bool) -> None:
        self.face3d._drawn(drawn)


def _connect(page, bridge: _Bridge) -> None:
    """Give ``page`` a web channel with ``bridge`` on it as ``window.kitDesk``, set up
    again on every load (the face page reloads itself when the brain has a new one)."""
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineScript

    channel = QWebChannel(page)
    channel.registerObject(BRIDGE, bridge)
    page.setWebChannel(channel)
    library = QFile(":/qtwebchannel/qwebchannel.js")  # carried inside Qt's web engine
    if not library.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Qt's web channel script is missing")
    source = bytes(library.readAll().data()).decode()
    script = QWebEngineScript()
    script.setName("kit-desk-bridge")
    script.setSourceCode(
        source + f"\nnew QWebChannel(qt.webChannelTransport, function (c) "
        f"{{ window.{BRIDGE} = c.objects.{BRIDGE}; }});"
    )
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    page.scripts().insert(script)


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
