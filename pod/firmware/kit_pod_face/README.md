# Kit Pod face

Kit's 2D face ("Kit 2D", look `kit2d_screen`) on the Pod, with the turn and tilt
servos, the pat sensor and uploads over Wi-Fi.

## Files

- `kit_pod_face.ino`: the program.
- `wifi_settings.h`: your Wi-Fi name and password, and the upload password. Copy `wifi_settings.example.h` to `wifi_settings.h` and fill it in before the first upload.
- `kit_server.h`: where Kit's server is and Kit's token, so the Pod follows Kit's real moods. Copy `kit_server.example.h` to `kit_server.h`. Leave `KIT_URL` empty and he runs on his own.
- Both real files are in `.gitignore`, so your Wi-Fi password and Kit's token never go into the repo.
- `kit2d_sheet.h`: Kit's moods, colours and gestures, made from Kit's character sheet (`src/kit/face/characters/kit2d.json`) by `make_sheet.py`. When the sheet changes, run `python make_sheet.py` and upload again.
- What the screen shows is in the docs: `docs/Assets/pod-screen-moods.png` and `docs/Assets/pod-screen-gestures.png`.

How it all works, with pictures: `docs/3 Deep Dives/Pod In Depth.md`. Building one: `docs/4 Guides/Building the Pod.md`.

## First upload (USB, one time)

1. Open `kit_pod_face.ino` in the Arduino app (keep all files in this folder).
2. Copy `wifi_settings.example.h` to `wifi_settings.h` and `kit_server.example.h` to `kit_server.h`, and fill them in.
3. Board: ESP32 Dev Module. Partition Scheme: "Default 4MB with spiffs" (any scheme without OTA blocks Wi-Fi uploads). Port: the USB one. Unplug the servo red wires, hold BOOT during "Connecting...", upload.
4. Open the Serial Monitor (115200). After a few seconds it says `On Wi-Fi as kit-pod (...)`.

## Every upload after that (Wi-Fi)

Tools > Port > `kit-pod at 192.168...`, then Upload. It asks for the upload password
(`kitpod` unless you changed it). The screen shows a bar, the servos go limp, then Kit restarts.
If the port doesn't show up, restart the Arduino app.

If it fails with "No response from device" after "Authenticating... OK":
- the screen didn't change: the partition scheme has no room for a Wi-Fi upload. Fix it as in step 3 and upload once over USB.
- the screen flicks to the update screen and straight back: the Pod's call back is going the wrong way. On a PC with Tailscale this was Tailscale's subnet routing; untick "Use Tailscale subnets" in its tray menu > Preferences.
- the screen showed the bar at 0%: the Pod can't reach the PC. Set the PC's network to Private and allow `espota.exe` through Windows Firewall.

## Settings at the top of the program

- `TURN_CENTRE`, `TILT_CENTRE`: change if Kit doesn't face straight ahead.
- `TURN_SIGN`, `TILT_SIGN`: set to -1 if he turns or nods the wrong way.
- `NECK_...` and `GLANCE_...`: the calm neck (below). Dead band, how long the head holds still, how fast it moves, how often he glances round.
- `DOZE_AFTER_MS`: how long alone before he falls asleep.

## Serial Monitor commands

A mood (`happy`, `sad`, ...), a gesture (`nod`, `wink`, `laugh`, ...), a state
(`sleep`, `wake`, `listen`, `think`, `talk`, `offline`, `awake`), `tour`, `still` or `help`.
Pat him once for a wiggle, three times quickly and he laughs.
`look` makes something catch his eye at a random spot; `look -0.8` (left -1 .. right 1)
or `look 0.5 -0.3` (then up -1 .. down 1) picks the spot. `glance` makes him look round now.

## The calm neck

The face is lively; the neck is not. The eyes dart about on the screen, but the head
only moves when Kit pays attention to something:
- a glance round the room now and then: about every 5 minutes when he's calm (focused,
  sleepy, sad), every 3 minutes in a neutral mood, and nearer every minute when he's lively;
- something catching his eye (`look`, later Kit's server and camera). The eyes jump first
  and the head follows, a bit quicker than a glance;
- a real gesture (a command, a pat, waking up). Idle fidgets stay on the face;
- his mood's posture, such as a droop when sad or head down asleep.

Turns under 9 degrees and tilts under 4 are left to the eyes, every move is eased, and the
head stays still at least 3 s after each move. On a PC simulation of 10 idle minutes the old
program moved the servos about 26 times a minute; this one under once a minute.

## Linked to Kit's brain

With `kit_server.h` filled in, the Pod asks Kit's server for the body feed over Wi-Fi
(see `docs/3 Deep Dives/Pod In Depth.md`). Then:
- his face rests on Kit's mood and feelings (the same face the desk shows between replies);
- while Kit answers a chat he looks thoughtful, shows the reply's emotion, and his mouth moves while the words are said;
- he sleeps and wakes when Kit does, and his own idle moods and dozing are switched off;
- Kit's fidgets play on the face only; Kit's reactions use the neck too;
- how lively Kit is sets how often he glances round;
- with Kit's eyes (the camera) running: someone appearing, or moving somewhere new, catches his eye and his head turns there; now and then he follows you for 8 to 25 s (more often when he's lively). Small moves are followed by the eyes only. The camera sits on the PC, not in the Pod, so where he looks is roughly right, not exact; when he talks to someone in the room by name ("Hi Sam!") his head turns to them for a few seconds;
- a pat on his head reaches Kit, who feels warm about it.

The Serial Monitor says "Linked to Kit's brain" once it hears from the server. If the
server is down for a minute he goes back to running on his own until it's back.
