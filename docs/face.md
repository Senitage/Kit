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
node his moves turn and bounce, shape keys for his face, and a face pack
(`face.json`) that says what each mood looks like (a mix of shape keys, a glow
colour, how lively he is, a move), what the weather shows bring (props with
looping animations for rain, storm, sun, wind, fog and a hot day), and how fast it all blends. The model
and pack sit in a folder named after the character next to its sheet:

```json
"kit3d": {
  "style": "model",
  "file": "kit_face.glb",
  "pack": "face.json",
  "fallback": "glow",
  "head_bone": "head",
  "gestures": {"nod": {"clip": "nod"}, "wink": {"clip": "idle", "face": {"close_R": 1}}}
}
```

`gestures` maps each of Kit's gestures to one of the model's animation clips,
plus an optional face pulse (shape keys eased in and out over the clip), so a
wink or a laugh shows on his face as well as in his moves. `fallback` names a
2D look for anything that can't draw 3D (the ESP32 screens, or an app without
the 3D page); it's what such an app gets if `use` picks the 3D look.

`kit3d` is the 3D character from Dan's Blender project ("Kit's 3D face in
Blender" thread). It uses the 3D look on the desk and in home_app and Glow on
a robot screen. Retro stays the default; set `face.character = "kit3d"` to
switch.

### The 3D face page (no new desk app per face)

Apps don't draw the 3D face themselves. The brain serves a face page at
`/face/` (three.js, vendored in `src/kit/web/face/vendor` so it works offline)
along with the character's model and pack (`kit.face.serve`). The desk app
lays that page, see-through, over its Glow window (`kit.desk.face3d`) and
copies the face's emotion, state, gestures, gaze and shows to it through the
page's `kit` API:

```js
kit.setEmotion("happy"); kit.play("laugh"); kit.setState("listening");
kit.lookAt(0.4, -0.2); kit.show({kind: "weather", text: "18°", sky: "storm"});
```

A weather show's `sky` (from `kit.shows`) picks the pack's show of the same
name: `storm`, `rain`, `wind`, `fog` and `hot`, with `sun` and `part_cloud`
bringing `sunny`. A pack without that show uses the nearest one it has (hot
falls back to sunny) or just shows the temperature.

The page asks the brain for a version every few seconds and reloads (keeping
his mood) when it changes: a new page, a different character, or a changed
model or pack. So a new model, retuned moods or a fix to how he moves reach
the desk as soon as the brain has them, with no new desk app. Clicks and drags
still go to the Glow window underneath, and if the desk app has no web engine
or the page can't load, Glow stays.

`face.pack_folder` points the brain at a pack folder outside Kit, such as the
`pack` folder the Blender project writes (from WSL, something like
`/mnt/c/Users/<you>/Documents/Blender/Kit/Kit_3D_Face/pack`).
Each rebuild then shows on the desk within seconds. Copy a finished pack into
`src/kit/face/characters/kit3d/` to ship it.

Open `http://<brain>:8600/face/?character=kit3d&bg=%2310151c` in a browser to
see the page on its own; add `&bloom=1` for the glow effect (off over a
see-through window, where it would darken the edges).

Blinks, eye darts, breathing, the reading sweep while working and the talking
pulse are reflexes and stay in the rig's code. A new eye *shape* (not just new
sizes or colours) needs a new painter `style` in each app.

## Body moves: hops, loops and big gestures

Gestures move his face within its own screen; body moves move all of him.
`kit.face.body` describes each one (a loop, a hop, a double hop, a jump back, a
sway, a sink, a bob, a dash, a peek) as a path in face sizes that starts and
ends where he sits, so the arm can use the same names later.

- A gesture with a bigger version brings it along (bounce hops twice, startle
  jumps back, droop sinks), an excited reply does a loop, and so does his hello
  when Dan gets back.
- On the desk, `kit.desk.alive.Body` moves his window: where Dan left him, plus
  the lift that makes room for his words, plus the move. His window has a
  see-through margin, so big tilts and squashes aren't cut off.
- The Look page's "How much Kit moves" sets how big his gestures are and
  whether body moves play: Lively (the default), Bouncy, A little (the old
  size, no body moves) or Still. He waits a few seconds between moves, and a
  loop at most every 40 seconds, so he's lively without being frantic.

## Shows: the time, the date, the weather

Glow can show things besides his eyes. Ask Kit the time and his eyes turn into
the time; ask the date and they become "FRI" over "9 OCT". Ask about the
weather and the temperature takes his eyes' place, then the sky plays on and
around him: rain or a storm from a little cloud over his head, sun, a
passing cloud, fog, or the moon and stars after dark. A dry day at 35°C or more
(`face.hot_c`) is a scorcher, with shimmering air and a drop of sweat; a dry day
with wind of 35 km/h or more has gusts and a leaf blowing past. Rain and storms
win over both. Snow shows as rain.

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
rounded rectangles, two lid cut-outs and a glow) and reads its sizes and
colours from the character sheet, and the rig's frame numbers travel over the
bus. The rig stays in Python on the Pi.
