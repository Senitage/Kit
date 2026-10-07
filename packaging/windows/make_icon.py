"""Draw Kit's Glow face into kit.ico for the installer, the exe and shortcuts.

Run from the repo root with the desk extra installed:
``python packaging/windows/make_icon.py packaging/windows/build/kit.ico``
"""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

from kit.desk.glow import paint_glow  # noqa: E402
from kit.face import Face  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def png(size: int) -> bytes:
    frame = replace(Face().tick(0.0), look_x=0.0, look_y=0.0, open_left=1.0, open_right=1.0)
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    paint_glow(p, QRectF(0, 0, size, size), frame)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data.data())


def ico(images: dict[int, bytes]) -> bytes:
    """A Windows .ico holding one PNG per size (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, offset = b"", 6 + 16 * len(images)
    for size, data in images.items():
        side = 0 if size >= 256 else size  # 0 means 256 in an icon directory
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(images.values())


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "kit.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    QGuiApplication.instance() or QGuiApplication([])
    out.write_bytes(ico({s: png(s) for s in SIZES}))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
