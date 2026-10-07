"""The eyes' loop: frames in, scene reports out, about once a second.

``Eyes`` holds the parts (a way to open the camera, a detector, the face and
body readers, a reporter that posts to the brain) and runs them; every part
is passed in, so the tests run it with fakes and no camera. ``build_eyes``
makes the real parts from Kit's settings.

The brain answers each report with whether the eyes are paused (the tray's
"Let Kit see me" switch, or ``kit eyes pause``) and the current ``[eyes]``
settings, so changes made on the settings page reach a running pair of eyes.
Paused eyes let the camera go and tell the brain they're off every few
seconds; nothing is looked at until the switch is on again.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

import numpy as np

from kit.eyes.scene import Scene
from kit.settings import EyesSettings

log = logging.getLogger(__name__)

PAUSED_POLL_S = 3.0  # while paused, ask the brain this often whether to look again
CAMERA_RETRY_S = 5.0  # the camera went away: try it again after this long
REPORT_RETRY_S = 5.0  # the brain can't be reached: say so once, try again later

Reporter = Callable[[dict], dict]


class Eyes:
    def __init__(
        self,
        open_camera: Callable[[], object | None],
        detector,
        reporter: Reporter,
        settings: EyesSettings | None = None,
        faces=None,
        body=None,
        camera_name: str = "desk",
        clock: Callable[[], float] = time.perf_counter,
        wall: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
        on_frame: Callable[[object, Scene, dict | None], bool] | None = None,
    ) -> None:
        self.settings = settings or EyesSettings()
        self.open_camera = open_camera
        self.detector = detector
        self.reporter = reporter
        self.faces = faces
        self.body = body
        self.camera_name = camera_name
        self.clock = clock
        self.sleep = sleep
        self.on_frame = on_frame  # the preview: returns False to stop
        self.scene = Scene(forget_after=self.settings.forget_after_s, clock=wall)
        self.camera = None
        self.paused = False
        self.error = ""  # the last trouble reaching the brain, for the log and `kit eyes`
        self.reports = 0
        self.fps = 0.0
        self._start = clock()
        self._last_frame = self._start
        self._last_report = self._start - 1e9
        self._camera_failed_at: float | None = None
        self._error_at: float | None = None

    # One pass of the loop

    def step(self) -> list[str]:
        """Look at one frame (or, paused, check in with the brain). Returns the
        scene's new event lines."""
        now = self.clock()
        if self.paused:
            self._release()
            if now - self._last_report >= PAUSED_POLL_S:
                self._send({"camera": self.camera_name, "off": True}, now)
            self.sleep(0.2)
            return []
        if self.camera is None and not self._open(now):
            self.sleep(0.5)
            return []
        frame = self.camera.read()
        if frame is None:
            log.warning("the camera stopped giving frames; reopening it")
            self._release()
            self._camera_failed_at = now
            return []
        if self.settings.mirror:
            frame = np.ascontiguousarray(frame[:, ::-1])
        h, w = frame.shape[:2]
        detections = self.detector.detect(frame)
        faces, hands, poses = [], [], []
        if self.faces is not None or self.body is not None:
            rgb = np.ascontiguousarray(frame[:, :, ::-1])
            image = self._image(rgb)
            ts = int((now - self._start) * 1000)
            if self.faces is not None:
                faces = self.faces.detect(image, (w, h), ts)
            if self.body is not None:
                hands, poses = self.body.read(image, ts)
        events = self.scene.update(now, (w, h), detections, faces, hands, poses)
        for event in events:
            log.info("%s", event)
        dt, self._last_frame = now - self._last_frame, now
        if dt > 0:
            self.fps = 0.9 * self.fps + 0.1 / dt if self.fps else 1 / dt
        report = None
        if now - self._last_report >= self.settings.report_every_s:
            report = self.scene.report(self.camera_name, self.settings.mirror, self.fps)
            self._send(report, now)
        if self.on_frame is not None and not self.on_frame(frame, self.scene, report):
            raise StopIteration
        return events

    def run(self, stop: threading.Event | None = None, max_steps: int | None = None) -> None:
        """Loop until ``stop`` is set, the preview is closed, or ``max_steps`` passes."""
        steps = 0
        try:
            while stop is None or not stop.is_set():
                try:
                    self.step()
                except StopIteration:
                    break
                steps += 1
                if max_steps is not None and steps >= max_steps:
                    break
        finally:
            self.close()

    def close(self) -> None:
        self._release()
        for part in (self.detector, self.faces, self.body):
            if part is not None and hasattr(part, "close"):
                part.close()

    # The parts

    @staticmethod
    def _image(rgb):
        """MediaPipe's image wrapper, built once per frame for both readers."""
        from kit.eyes.body import mp_image

        return mp_image(rgb)

    def _open(self, now: float) -> bool:
        if self._camera_failed_at is not None and now - self._camera_failed_at < CAMERA_RETRY_S:
            return False
        self.camera = self.open_camera()
        if self.camera is None:
            if self._camera_failed_at is None:
                log.error("can't open camera %s", self.settings.camera)
            self._camera_failed_at = now
            return False
        self._camera_failed_at = None
        return True

    def _release(self) -> None:
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def _send(self, report: dict, now: float) -> None:
        self._last_report = now
        try:
            answer = self.reporter(report)
        except Exception as e:  # the brain is down or said no: keep looking, say so once
            if self.error != str(e):
                log.warning("can't report to the brain: %s", e)
            self.error = str(e)
            self._last_report = now - self.settings.report_every_s + REPORT_RETRY_S
            return
        if self.error:
            log.info("back in touch with the brain")
            self.error = ""
        self.reports += 1
        self.apply(answer or {})

    def apply(self, answer: dict) -> None:
        """What the brain said back: paused or not, and the settings in force."""
        paused = bool(answer.get("paused", False))
        if paused != self.paused:
            log.info("eyes %s", "paused: the camera is off" if paused else "on again")
            self.paused = paused
            if paused:
                self._release()  # straight away, not on the next pass
        raw = answer.get("settings")
        if isinstance(raw, dict):
            try:
                fresh = EyesSettings.model_validate(raw)
            except ValueError:
                return
            if fresh != self.settings:
                restart = {"camera", "width", "height", "detector", "faces", "hands", "poses"}
                changed = {
                    k
                    for k in EyesSettings.model_fields
                    if getattr(fresh, k) != getattr(self.settings, k)
                }
                if changed & restart:
                    log.info(
                        "settings changed (%s); restart `kit eyes` for them",
                        ", ".join(sorted(changed & restart)),
                    )
                self.settings = fresh
                self.scene.memory.forget_after = fresh.forget_after_s


def build_eyes(
    settings: EyesSettings,
    reporter: Reporter,
    camera: int | None = None,
    camera_name: str = "desk",
    on_frame=None,
    folder=None,
) -> Eyes:
    """The real eyes: OpenCV camera, YOLO detector, MediaPipe readers. Imports the
    camera and model libraries here, so only this needs them installed."""
    from kit.eyes.camera import open_camera
    from kit.eyes.detect import YoloDetector
    from kit.eyes.link import models_dir

    models = models_dir(folder)
    index = settings.camera if camera is None else camera
    detector = YoloDetector(settings.detector, models, settings.confidence)
    faces = body = None
    if settings.faces:
        from kit.eyes.faces import FaceAnalyzer

        faces = FaceAnalyzer(models)
    if settings.hands or settings.poses:
        from kit.eyes.body import BodyReader

        body = BodyReader(models, hands=settings.hands, poses=settings.poses)
    return Eyes(
        lambda: open_camera(index, settings.width, settings.height),
        detector,
        reporter,
        settings,
        faces=faces,
        body=body,
        camera_name=camera_name,
        on_frame=on_frame,
    )
