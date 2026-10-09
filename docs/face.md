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

## Shows: the time, the date, the weather

Glow can show things besides his eyes. Ask Kit the time and his eyes turn into
the time; ask the date and they become "FRI" over "9 OCT". Ask about the
weather and the temperature takes his eyes' place, then the sky plays on and
around him: rain or a storm from a little cloud over his head, snow, sun, a
passing cloud, fog, or the moon and stars after dark.

- `kit.shows` (brain) picks a show from Dan's words and fills in the facts from
  the clock and Open-Meteo (`Weather.today`, which can also give tomorrow). It
  goes out as a `show` event beside the reply. The weather is only shown for
  home, today or tomorrow; "the weather in Sydney" or "this weekend" shows
  nothing.
- `kit.desk.scenes` (desk app) draws each show. A scene paints on his screen
  (moving with his head) and in front of him (staying put), and says how much
  of his eyes show. The desk app starts it as his answer starts.
- To add a show: a kind in `kit.shows` and a scene in `kit.desk.scenes.SCENES`.
  A body that doesn't know a kind ignores it.

## Try it

```
pip install -e ".[desk]"
python -m kit.desk.face_preview           # buttons for every emotion, gesture, state and show
python -m kit.desk.face_preview --float   # a small always-on-top face you can drag
```

## On the arm

The face head gets a 1.28 in round GC9A01 screen (240×240) behind smoked
acrylic. An ESP32 drives the screen. The painter is ported to C++ (it uses only
rounded rectangles, two lid cut-outs and a glow), and the rig's frame numbers
travel over the bus. The rig stays in Python on the Pi.
