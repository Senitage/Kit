# Vision, stage 1: Kit sees you

Kit gets eyes. A small camera process runs on the PC with the webcam (the desk
PC now, the Raspberry Pi at the arm later) and tells the brain, in words and
numbers, what it sees: who's at the desk, where they are, where they're
looking, their expression, their hands, what they're holding, and what just
happened. Never a picture. The brain keeps that as a scene, the way it keeps
what's on your PC, and Kit:

- **knows you're there** even when you're only reading or on the phone, and
  doesn't doze off while someone's in view;
- **says hello** when someone sits down after the desk has been empty a while
  (`life.greet_after_minutes`, 20 by default). He can't tell faces apart yet,
  so it's "someone, most likely Dan" and he may well ask;
- **looks at you**: Glow's eyes follow your face. The arm will turn to you the
  same way;
- **notices things**: the cat wandering in, a wave, a thumbs up, a cup in your
  hand. They go into his thoughts; arrivals after a long gap and animal
  sightings go into his memory (`seen`), so "when did I get in this morning?"
  has an answer;
- **has a proper look** when you ask ("what can you see?", "what am I
  holding?", "is the cat around?") or when he decides he needs to
  (`look_around`, like `look_at_pc`).

The later stages: who's who (names, enrolment, the register), gestures and
moods, a proper look at a still frame with a vision model, and eyes on the Pi.
How it all fits together is at the end.

## 1. Update and restart Kit (the server)

```
cd ~/Kit
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
```

No new packages on the server, no new keys, no memory upgrade. The brain
accepts eyes reports from the moment it's back.

## 2. Install the eyes on the desk PC

The eyes need Python 3.11+ on the PC with the webcam, in their own venv
(the installed desk app can't carry the model libraries). In PowerShell:

```powershell
cd C:\path\to\Kit        # a clone of this repo
python -m venv .eyes
.eyes\Scripts\activate
# PyTorch with CUDA first, so the detector uses the GPU (skip it for CPU only):
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[eyes]"
```

`kit[eyes]` brings OpenCV (the contrib build, which MediaPipe needs; don't
install plain `opencv-python` beside it), Ultralytics, ByteTrack's `lap` and
MediaPipe. The models (YOLO11n, about 6 MB; MediaPipe's face, gesture and pose
tasks, about 30 MB) download into the eyes' folder the first time they run.

On the Pi later it's the same command on Raspberry Pi OS 64-bit; Ultralytics
pulls the CPU build of PyTorch there, and stage 5 adds the NCNN export.

## 3. Tell the eyes where the brain is

If the desk app is set up on this PC, nothing to do: the eyes use its brain
address and token. Otherwise, once:

```
kit eyes connect http://kit-server:8600 THE-TOKEN      # `kit token` on the server
```

That saves to `%APPDATA%\Kit Eyes` (`~/.config/kit-eyes` elsewhere, or
`KIT_EYES_DIR`); the token sits in its own file there, never in a settings
file. The eyes read everything else (which camera, mirroring, the detector,
how often to report) from Kit's settings under `[eyes]`, so there is one
place to change them: the settings page, `kit config set eyes.camera 1`, or
home_app later. A running pair of eyes picks changes up as it goes; camera
and model changes need a restart.

## 4. Open them

```
kit eyes cameras      # which cameras this PC has: pick one with eyes.camera
kit eyes --show       # a window with boxes, ids, faces and the scene in words
kit eyes              # headless, for every day; Ctrl+C closes them
```

The terminal prints each event as it happens ("person #1 entered", "person #1
right hand: thumbs up"). `kit eyes show` (on either machine) prints what the
brain has been told, exactly as Kit reads it, and `GET /api/status` has a
one-line `eyes` entry.

To start them with Windows, make a scheduled task (Task Scheduler, "At log
on") that runs `C:\path\to\Kit\.eyes\Scripts\kit.exe eyes`, or put a shortcut
to it in `shell:startup`. A proper service and the tray app starting them is
later work.

## 5. The switch

**Let Kit see me** in the tray menu (and `kit eyes pause` / `resume`) switches
his eyes off and on. Off, the camera process releases the camera and tells
the brain it's off every few seconds; Kit is told he can't see. The brain
keeps the switch, so it holds across restarts of either side. `eyes.enabled =
false` in settings does the same for good.

## 6. What it costs

Nothing in money: everything runs on the desk PC. The detector takes a few
milliseconds a frame on the GPU (40 to 80 ms on a desktop CPU), MediaPipe 10 to
30 ms per task on the CPU, so expect 15 to 30 frames a second with faces,
hands and one pose on. Turn `eyes.poses` to 0 or `eyes.hands` off to spend
less. Reports to the brain are under a kilobyte, once a second. The server's
GPU is untouched; the 2070 Super keeps its memory for the local model.

## 7. Privacy

- No frame leaves the PC. The brain only ever gets words and numbers: boxes
  as fractions of the frame, "smiling", "thumbs up", "holding cup". The preview
  window is local.
- Nothing is stored about faces yet. Stage 2 keeps embeddings only (numbers,
  never images), in Kit's data folder, for people who said yes.
- What goes into memory is small: "someone sat down at the desk after 45 min",
  "a cat wandered in". Kit's memory page shows it under `seen`, and it can be
  forgotten like anything else.
- The switch above turns the camera off; the brain says so in every prompt
  while it's off, so Kit never pretends to see.

## 8. Test checklist

- [ ] On the server after the update, `kit check` has an `eyes` line (a warning
      that there's no camera on the server is fine).
- [ ] On the desk PC, `kit eyes cameras` lists the webcam. `kit eyes --show`
      opens a window with a box around you, your face outlined, and the words
      at the bottom ("Person #1: centre; in view 5s; facing the camera").
- [ ] Hold a cup up. Within a couple of seconds the window and the terminal
      say "holding cup"; drink from it and "drinking" appears.
- [ ] Give a thumbs up, then wave. "right hand: thumbs up" and "waving" show.
- [ ] `kit eyes show` on either machine prints the same scene in Kit's words.
      `kit eyes` headless does the same job without the window.
- [ ] Ask Kit "can you see me?" and "what am I holding?". The chat shows
      "looking around", the answer comes from the local model and is right.
- [ ] Ask "who's here?" with nobody at the desk. He says the desk is empty.
- [ ] Walk away for half an hour (or set `life.greet_after_minutes = 1` and
      walk away for a minute). When you sit back down he says hello within a
      minute or so, in his own words, and doesn't sulk when you don't answer.
- [ ] With Glow on screen, move left and right in front of the camera. Glow's
      eyes follow you (left when you go to your left: `eyes.mirror` is right).
- [ ] Stay at the desk reading, hands off the keyboard, for longer than
      `life.sleep_after_minutes`. He stays awake; `kit life` shows him present.
      Leave the desk and he dozes off after that long; come back and he wakes.
- [ ] Let the cat in (or show the camera a photo of one). The terminal says
      "cat #N entered", `kit life` shows him curious, and the memory page has a
      `seen` entry for it.
- [ ] Untick **Let Kit see me** in the tray. The eyes log "paused: the camera
      is off", the webcam light goes out, `kit eyes show` says they're off, and
      Kit says he can't see when asked. Tick it again: the light comes back.
- [ ] Change `eyes.mirror` on the settings page. The running eyes log the
      change and Glow's follow reverses; change it back.
- [ ] Stop the brain for a minute with the eyes running. They say so once,
      keep looking, and carry on when it's back.
- [ ] Unplug the webcam. The eyes say so and try again every few seconds; plug
      it back in and they carry on.

## How it fits together

- `kit.eyes` (the camera side, needs `kit[eyes]`): `camera` (OpenCV),
  `detect` (YOLO11 via Ultralytics with ByteTrack ids, behind a `Detector`
  shape so an NCNN, Hailo or MediaPipe detector can stand in), `faces` and
  `body` (MediaPipe: head direction, expressions, hands and gestures, pose),
  `actions` (nodding, waving, talking, drinking, typing... from a couple of
  seconds of history), `scene` (one picture, flicker-proof events, the report),
  `run` (the loop, with every part passed in so tests use fakes), `link` (the
  eyes' folder and finding the brain) and `preview` (the window).
- `kit.scene_context` (brain side, plain Python): the latest report and the
  day's comings and goings, the prompt line, `look_around`, and what just
  happened (arrived, left, animal) for `kit.life`.
- `kit.life`: presence from the eyes as well as the keyboard, sleeping and
  waking, the hello, `look` events for the bodies ([life.md](life.md)).
- API: `POST /api/eyes/scene` (the report; the answer carries the switch and
  the eyes' settings), `GET /api/eyes/scene`, `POST /api/eyes/pause`.
- The desk app: acts out `look` events on Glow, and the tray switch.
- Dan's Computer Vision repo was the prototype; its modules came across with
  Kit's conventions (settings from the brain, the eyes' own folder, fakes in
  tests, mirroring as a setting).

Next: stage 2, who's who. `kit eyes enrol NAME` from the camera or photos,
named arrivals and greetings, the cat by name in the register, "who's that?"
for an unknown face, and sightings by name in memory and the day summary.
