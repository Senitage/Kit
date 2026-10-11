"""A window showing what the eyes see (``kit eyes --show``), drawn with OpenCV.
Only for checking the camera and the models on the desk; nothing in it is sent
anywhere."""

from __future__ import annotations

from kit.eyes.scene import Scene, describe

WINDOW = "Kit's eyes"


def colour_for(track_id: int) -> tuple[int, int, int]:
    """A stable, bright BGR colour per track id."""
    h = track_id * 2654435761  # spreads consecutive ids across very different colours
    return (80 + h % 176, 80 + (h // 176) % 176, 80 + (h // 30976) % 176)


def draw(frame, scene: Scene, report: dict | None, fps: float) -> None:
    import cv2

    font = cv2.FONT_HERSHEY_SIMPLEX
    for track in scene.in_view():
        x1, y1, x2, y2 = track.box
        colour = colour_for(track.id)
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
        name = scene.name_of(track.id) or track.label
        text = f"#{track.id} {name} {track.age(scene.now):.0f}s"
        (tw, th), _ = cv2.getTextSize(text, font, 0.6, 2)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), colour, -1)
        cv2.putText(frame, text, (x1 + 3, y1 - 5), font, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
        info = scene.people.get(track.id)
        if info and info["face"] is not None:
            fx1, fy1, fx2, fy2 = info["face"].box
            cv2.rectangle(frame, (fx1, fy1), (fx2, fy2), (255, 255, 255), 1)
    cv2.putText(frame, f"{fps:4.1f} fps", (10, 30), font, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
    lines = describe(report, max_events=0) if report else []
    y = frame.shape[0] - 15 - 22 * (len(lines) - 1)
    for line in lines:
        cv2.putText(frame, line, (10, y), font, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (10, y), font, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        y += 22


def show(frame) -> bool:
    """Show the frame; False once the window is closed or q pressed."""
    import cv2

    cv2.imshow(WINDOW, frame)
    key = cv2.waitKey(1) & 0xFF
    return key not in (ord("q"), 27) and cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1


def previewer(eyes_fps: callable):
    """An ``on_frame`` for ``Eyes`` that draws and shows each frame."""
    last: dict | None = None

    def on_frame(frame, scene: Scene, report: dict | None) -> bool:
        nonlocal last
        if report is not None:
            last = report
        draw(frame, scene, last, eyes_fps())
        return show(frame)

    return on_frame
