"""Finding people and objects, with ids that follow them between frames.

``Detector`` is the shape the scene needs: a list of (track id, label, box)
per frame. ``YoloDetector`` is today's one (YOLO11 through Ultralytics, with
ByteTrack keeping the ids). Ultralytics is AGPL-licensed and heavy, so it is
imported only when a ``YoloDetector`` is built; a Raspberry Pi export (NCNN),
a Hailo chip or a MediaPipe detector can stand in behind the same shape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

Box = tuple[int, int, int, int]
Detection = tuple[int, str, Box]


class Detector(Protocol):
    def detect(self, frame) -> list[Detection]: ...

    def close(self) -> None: ...


def pick_device() -> int | str:
    """The GPU if PyTorch can see one, else the CPU."""
    try:
        import torch
    except ImportError:
        return "cpu"
    return 0 if torch.cuda.is_available() else "cpu"


def device_name(device: int | str) -> str:
    if device == "cpu":
        return "CPU"
    try:
        import torch

        return torch.cuda.get_device_name(device)
    except Exception:  # no torch, or no such device
        return f"GPU {device}"


class YoloDetector:
    """YOLO through Ultralytics. ``weights`` is a model name ("yolo11n") or a file;
    a name is downloaded into ``folder`` the first time. ``model.track`` is
    detect + link to the previous frame; ``persist=True`` keeps the tracker's
    state between calls, which is what makes the ids carry over."""

    def __init__(
        self,
        weights: str = "yolo11s",
        folder: Path | None = None,
        confidence: float = 0.4,
        device: int | str | None = None,
    ) -> None:
        from ultralytics import YOLO

        name = weights if weights.endswith((".pt", ".onnx")) or "/" in weights else f"{weights}.pt"
        path = Path(folder) / name if folder is not None and "/" not in name else Path(name)
        if folder is not None:
            Path(folder).mkdir(parents=True, exist_ok=True)
        self.model = YOLO(str(path))
        self.confidence = confidence
        self.device = pick_device() if device is None else device
        log.info("detector %s on %s", path.name, device_name(self.device))

    def detect(self, frame) -> list[Detection]:
        result = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=self.confidence,
            device=self.device,
            verbose=False,
        )[0]
        if result.boxes.id is None:  # nothing being tracked
            return []
        return [
            (int(track_id), result.names[int(cls)], tuple(int(v) for v in box))
            for box, track_id, cls in zip(
                result.boxes.xyxy, result.boxes.id, result.boxes.cls, strict=True
            )
        ]

    def close(self) -> None:
        pass
