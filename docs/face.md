# Kit's face

Kit's face is **Glow**: two glowing pill eyes on a dark rounded screen. Dan
picked it on 2026-10-05 from four styles in the
[Kit Face Studio](https://claude.ai/artifact/EJacAg7UBPBiyNX8cF31bd) mockups.

## How it's built

- `kit.face` is the expression rig. It holds no drawing code. Each frame it
  turns what's happening into numbers: eye openness, squint, lid tilt, gaze,
  glow, and head tilt, bob and squash. It has three layers:
  1. Reflexes run all the time: blinks (sometimes double), eye darts, breathing,
     and following `look_at` (the mouse now, Dan's face once the camera arrives).
  2. Each reply's `emotion` sets a pose that the face eases into and holds.
  3. Each segment's `gesture` plays a short clip a beat before its words.
- States cover what the helper shows between replies: `idle`, `sleeping`,
  `listening`, `thinking`, `speaking`, `working` and `offline`.
- `plan_reply(reply)` turns a reply from the brain into timed cues (emotion,
  then gesture, then words). Stage 2's helper and the arm both use it.
- `kit.desk.glow.paint_glow` paints one frame with QPainter, and `FaceWidget`
  runs the rig at 60 fps. Stage 2's helper window uses the widget.

Every emotion and gesture in `kit.reply` must have a pose and a clip. A test
enforces this, so adding an emotion means adding its pose too.

## Try it

```
pip install -e ".[desk]"
python -m kit.desk.face_preview           # buttons for every emotion, gesture and state
python -m kit.desk.face_preview --float   # a small always-on-top face you can drag
```

## On the arm

The face head gets a 1.28 in round GC9A01 screen (240×240) behind smoked
acrylic. An ESP32 drives the screen. The painter is ported to C++ (it uses only
rounded rectangles, two lid cut-outs and a glow), and the rig's frame numbers
travel over the bus. The rig stays in Python on the Pi.
