"""Finding people and objects, with ids that follow them between frames.

``Detector`` is the shape the scene needs: a list of (track id, label, box)
per frame. ``YoloDetector`` is today's one (YOLO11 through Ultralytics, with
ByteTrack keeping the ids). Ultralytics is AGPL-licensed and heavy, so it is
imported only when a ``YoloDetector`` is built; a Raspberry Pi export (NCNN),
a Hailo chip or a MediaPipe detector can stand in behind the same shape.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
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


def free_gpu() -> None:
    """Hand the memory of models just dropped back to the graphics card: PyTorch
    keeps freed memory cached for itself otherwise. Nothing without PyTorch."""
    torch = sys.modules.get("torch")
    if torch is None:
        return
    gc.collect()
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:  # a driver hiccup isn't worth stopping the eyes for
        log.debug("couldn't empty the GPU cache: %s", e)


def device_name(device: int | str) -> str:
    if device == "cpu":
        return "CPU"
    try:
        import torch

        return torch.cuda.get_device_name(device)
    except Exception:  # no torch, or no such device
        return f"GPU {device}"


def export_name(weights: str, fmt: str, size: int) -> str:
    """Where an exported copy of ``weights`` lives in the models folder. The size is
    in the name because an export only works at the size it was made for."""
    stem = Path(weights).stem
    return f"{stem}_{size}.onnx" if fmt == "onnx" else f"{stem}_{size}_{fmt}_model"


# What each export format needs installed, said plainly when it isn't. Ultralytics
# would otherwise pip-install it mid-run; YOLO_AUTOINSTALL stops that.
RUNTIMES = {"openvino": "openvino", "onnx": "onnx onnxruntime", "ncnn": "ncnn pnnx"}
os.environ.setdefault("YOLO_AUTOINSTALL", "false")


def missing_runtime(fmt: str, e: ImportError) -> RuntimeError:
    return RuntimeError(
        f"the {fmt} detector needs its runtime in the eyes' venv:"
        f" pip install {RUNTIMES.get(fmt, fmt)} ({e})"
    )


def exported(base: Path, fmt: str, size: int) -> Path:
    """The ``fmt`` export of the PyTorch model at ``base``, made the first time
    (Ultralytics downloads ``base`` if it isn't there yet)."""
    target = base.parent / export_name(base.name, fmt, size)
    if target.exists():
        return target
    from ultralytics import YOLO

    log.info("making the %s detector at %d px (once; this takes a minute)", fmt, size)
    try:
        made = Path(YOLO(str(base)).export(format=fmt, imgsz=size, verbose=False))
    except ImportError as e:
        raise missing_runtime(fmt, e) from e
    made.rename(target)
    return target


class YoloDetector:
    """YOLO through Ultralytics. ``weights`` is a model name ("yolo11n") or a file;
    a name is downloaded into ``folder`` the first time. ``fmt`` other than
    "pytorch" runs an OpenVINO, ONNX or NCNN copy made from it at ``size``, which
    is quicker on a CPU. ``model.track`` is detect + link to the previous frame;
    ``persist=True`` keeps the tracker's state between calls, which is what makes
    the ids carry over."""

    def __init__(
        self,
        weights: str = "yolo11s",
        folder: Path | None = None,
        confidence: float = 0.4,
        device: int | str | None = None,
        fmt: str = "pytorch",
        size: int = 640,
    ) -> None:
        from ultralytics import YOLO

        name = weights if weights.endswith((".pt", ".onnx")) or "/" in weights else f"{weights}.pt"
        path = Path(folder) / name if folder is not None and "/" not in name else Path(name)
        if folder is not None:
            Path(folder).mkdir(parents=True, exist_ok=True)
        if fmt != "pytorch" and path.suffix == ".pt":
            path = exported(path, fmt, size)
            device = "cpu"  # the exports are the CPU's way to run it
        try:
            self.model = YOLO(str(path), task="detect")
        except ImportError as e:
            raise missing_runtime(fmt, e) from e
        self.confidence = confidence
        self.size = size
        self.device = pick_device() if device is None else device
        log.info("detector %s on %s at %d px", path.name, device_name(self.device), size)

    def detect(self, frame) -> list[Detection]:
        result = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=self.confidence,
            imgsz=self.size,
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
        self.model = None  # dropped, so free_gpu can hand its memory back
