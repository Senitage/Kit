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

## The character sheet

Everything that makes Kit look like Kit lives in one file per character in
`src/kit/face/characters/`. `retro.json` is the original Glow pill eyes. The
`face.character` setting (`[face]` in settings.toml, or the settings page)
picks which character he is, so a new design sits beside Retro and switching
back is one setting. A character sheet holds:

- `looks`: each way of drawing him. `glow` is the 2D pill eyes: colours and
  the size and place of his screen, eyes, glow and blush, as fractions of the
  face's size. A `model` look is 3D (see below).
- `use`: which look each app or body draws: `desk`, `home_app`, `robot`, and
  `default` for anything not named. So the desk app can be 3D while a small
  robot screen stays 2D, from the same moods and gestures.
- `poses`: one per emotion. Any knob left out takes its value from
  `pose_default`.
- `states`: how asleep, offline, thinking and listening bend the pose, and how
  bright he glows in each.
- `gestures`: each gesture's length and its moves. A move is a list of terms
  per channel, each an amount times some shapes over the clip's time
  (`bump`, `hold`, `sin`, `abs_sin`, `line`, `jolt`); `kit.face.character`
  explains them.

The brain serves the chosen sheet at `GET /api/face` and lists the characters at
`GET /api/face/presets`. The desk app loads the sheet when it connects and
whenever `face.character` changes (keeping its own copy if the brain is older), and home_app's Kit
page loads it the same way, so a redesign is one new sheet and every
app follows. `kit.face.character.check` says in plain words what is wrong with
a broken sheet, and a broken sheet is never used.

### A 3D look

A 3D Kit is a glTF model (one `.glb` file, exported from Blender) with a head
bone the gestures move, bounce and turn, and morph targets (Blender's shape
keys) for his face that the poses drive:

```json
"kit3d": {
  "style": "model",
  "file": "kit.glb",
  "fallback": "glow",
  "head_bone": "head",
  "morphs": {"open": "EyesOpen", "squint": "Squint", "tilt": "LidAngle", "blush": "Blush"}
}
```

`morphs` maps the pose knobs to the model's morph target names. `fallback`
names a 2D look for anything that can't draw 3D (the ESP32 screens, or an app
before its 3D painter exists); it's what such an app gets if `use` picks the
3D look. No app draws 3D yet: adding `"desk": "kit3d"` today shows the
fallback until the desk app's 3D painter lands.

Blinks, eye darts, breathing, the reading sweep while working and the talking
pulse are reflexes and stay in the rig's code. A new eye *shape* (not just new
sizes or colours) needs a new painter `style` in each app.

## Try it

```
pip install -e ".[desk]"
python -m kit.desk.face_preview           # buttons for every emotion, gesture and state
python -m kit.desk.face_preview --float   # a small always-on-top face you can drag
```

## On the arm

The face head gets a 1.28 in round GC9A01 screen (240×240) behind smoked
acrylic. An ESP32 drives the screen. The painter is ported to C++ (it uses only
rounded rectangles, two lid cut-outs and a glow) and reads its sizes and
colours from the character sheet, and the rig's frame numbers travel over the
bus. The rig stays in Python on the Pi.
