"""Cameras through OpenCV. ``cv2`` is imported only when a camera is opened or
listed, so the brain and the tests never need it. The Raspberry Pi's camera
module (picamera2) is a later backend behind the same ``Camera`` shape.
"""

from __future__ import annotations

import sys


def _cv2():
    import cv2

    # Probing empty camera slots makes OpenCV print noisy warnings; only show errors.
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    return cv2


def backends() -> list[int]:
    """DirectShow opens quickly and reliably on Windows; MSMF is the fallback."""
    cv2 = _cv2()
    return [cv2.CAP_DSHOW, cv2.CAP_MSMF] if sys.platform == "win32" else [cv2.CAP_ANY]


class Camera:
    """An open camera: ``read`` gives a BGR frame or None, ``release`` lets it go."""

    def __init__(self, cap, index: int, backend: str) -> None:
        self.cap = cap
        self.index = index
        self.backend = backend

    @property
    def size(self) -> tuple[int, int]:
        cv2 = _cv2()
        return int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(
            self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )

    def read(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def release(self) -> None:
        self.cap.release()


def open_camera(index: int, width: int | None = None, height: int | None = None) -> Camera | None:
    """Open a camera by index, trying each backend; None if it won't deliver frames."""
    cv2 = _cv2()
    for backend in backends():
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        if width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        ok, _ = cap.read()
        if ok:
            return Camera(cap, index, cap.getBackendName())
        cap.release()
    return None


def list_cameras(max_index: int = 5) -> list[dict]:
    """Probe camera indices 0..max_index-1; the ones that deliver frames."""
    cv2 = _cv2()
    found = []
    for index in range(max_index):
        camera = open_camera(index)
        if camera is None:
            continue
        w, h = camera.size
        found.append(
            {
                "index": index,
                "backend": camera.backend,
                "width": w,
                "height": h,
                "fps": camera.cap.get(cv2.CAP_PROP_FPS),
            }
        )
        camera.release()
    return found


def camera_line(cam: dict) -> str:
    fps = f"{cam['fps']:.0f} fps" if cam.get("fps", 0) > 0 else "unknown fps"
    return f"[{cam['index']}] {cam['width']}x{cam['height']} at {fps} via {cam['backend']}"
