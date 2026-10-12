---
tags: [reference, topic/api]
aliases: [HTTP API, Endpoints, Kit's API, Routes]
summary: Every web address the brain answers on - chat, settings, memory, the register, life events, the PC and eyes feeds, speech, spend and the 3D face - and how the token works.
---

# API

Up: [[Home]] · Reference

The brain is a small web server (FastAPI) on port `brain.port` (8600). The
desk app, the eyes, home_app and the pages all use the same API. FastAPI also
serves its own interactive list at `/docs`.

## The token

Every `/api/...` call except `/api/health` needs Kit's token:

```
Authorization: Bearer TOKEN
```

`kit token` shows it. A paired device, like a phone, uses a token of its own
instead (`kit pair`): it opens the same API, and `kit devices forget` stops
it. See [[Phone App#Pairing]].

The pages (`/`, `/settings`, `/memory`) and the 3D face (`/face/...`) load
without one: the pages ask for it, and the face is only a
cartoon. The face files carry an ETag, so a page that already has one (the
phone's, on mobile data) gets "not changed" instead of the whole model again. See [[Privacy#Tokens and secrets]].

## Talking

| Method and path | What it does |
|---|---|
| `POST /api/chat` | Send `{"text": ..., "channel": "desk"}`. The answer streams back as one JSON event per line (below) |
| `POST /api/chat/new` | Start a fresh conversation |
| `GET /api/messages?limit=50` | The current conversation, each message with its `id` and replies |
| `GET /api/messages?before=ID` | A page of the whole history just before message `ID`, oldest first, even from before a new chat (`after=ID` for the ones after it) |

A chat message can also carry `body` (the body it came through, from its
hello), `sent_at` (when it was written, if it waited to be sent) and `spoken`
(said out loud). Each is kept in the message's `meta`. See
[[Phone App#What a message carries]].

A chat streams events like these, one per line:

| Event | Means |
|---|---|
| `mood` | His feeling going in, so the face and voice can react at once |
| `say` | Words as they're written (a cloud answer's too, as it streams in) |
| `sound` | A sound for his voice before the words that come next (`chuckle`, `sigh`, `gasp`), with `speech.sounds`. Never shown |
| `show` | Something for his face: the time, the date, the weather |
| `recalled`, `remembered`, `reading_note`, `looked_at_pc`, `looked_around` | What he did mid-answer |
| `handing_off` | A bigger model is taking over ("Let me think...") |
| `notice` | A line for the chat, like a budget warning |
| `reply` | The whole reply: words, emotion, gestures, actions |
| `spoken` | His words are complete, for the voice |
| `error` | Something went wrong, in words |

The reply's shape is in [[Brain#One shape for every reply]].

## Settings

| Method and path | What it does |
|---|---|
| `GET /api/settings` | The settings in force |
| `GET /api/settings/schema` | The settings schema (JSON Schema), which the settings pages are drawn from |
| `PATCH /api/settings` | Change settings. Merges one level deep, so send a model profile whole |
| `GET /api/settings/history` | Earlier versions |
| `POST /api/settings/undo` | Go back one change |

## Memory and the register

| Method and path | What it does |
|---|---|
| `GET /api/memory/facts` | What he knows |
| `POST /api/memory/facts` | Teach him a fact |
| `PATCH /api/memory/facts/{id}` | Edit or pin a fact |
| `GET /api/memory/facts/{id}/history` | A fact's earlier versions |
| `DELETE /api/memory/facts/{id}` | Forget a fact |
| `GET /api/memory/search?q=...` | Search the way Kit does |
| `GET /api/memory/days` | Day summaries |
| `GET /api/things` | The register of things |
| `GET /api/things/suggestions` | Names he suggested adding |
| `POST /api/things`, `PATCH /api/things/{id}` | Add or change a thing |
| `POST /api/things/{id}/confirm`, `/reject` | Accept or drop a suggestion |
| `GET /api/things/{id}/history`, `DELETE /api/things/{id}` | History, or forget it |

## His inner life

| Method and path | What it does |
|---|---|
| `GET /api/life` | Mood, feeling and why, drives, thoughts, what's coming up |
| `GET /api/life/events?after=N&wait=25` | Events for bodies, waiting up to `wait` seconds for a new one |
| `GET /api/life/notebook` | His notebook |
| `DELETE /api/life/notebook/{id}` | Forget a notebook entry |
| `POST /api/life/sheet/restore` | Give back an earlier self-sheet |
| `POST /api/life/quirks/retire`, `/restore` | Drop a quirk, or bring one back |
| `POST /api/life/think`, `/reflect`, `/poke` | A thought, tonight's look back, or a pipe-up, now |
| `POST /api/life/snooze` | Keep him quiet for `minutes` (0 lets him talk again) |

Bodies listen to `/api/life/events`: `mood`, `fidget`, `react`, `state`
(asleep or awake), `look`, `doing`, `quiet`, `dials` and `pipe_up`. See
[[Bodies]]. A `quiet` event says why he's keeping quiet (`because`) and, while
his eyes see you busy, what his bubble should say (`bubble`). A `pipe_up`
carries the line (`reply`), the line as his voice says it with any sounds
(`voice`), whether to say it out loud (`aloud`: false when his eyes see
nobody there), and which body says it (`to`, a body id: the PC Dan's using,
else the device he last talked through). Other bodies only show the words.

## Kit's bodies and paired devices

| Method and path | What it does |
|---|---|
| `POST /api/bodies/hello` | A body says what it is and can do: `{"id", "kind", "name", "app", "abilities": ["screen", "speaker", ...], "faces"}`. A paired device is known by its device name |
| `GET /api/bodies` | The bodies heard from since the brain started (online, last seen, last used) and the paired devices. Each PC running the desk app is one, `desk:` and its name |
| `POST /api/devices/pair` | Pair a device from the device: send `{"name": "phone", "kind": "phone"}` with Kit's own token, get back the device's token. Pairing a name again replaces its token |
| `DELETE /api/devices/{name}` | Unpair a device (Kit's token, or the device's own) |
| `POST /api/devices/{name}/push`, `DELETE` | The device's push token, so Kit can nudge it when he pipes up and its app is closed: `{"kind": "fcm", "token": "..."}` (the device's own token, or Kit's). The answer's `nudges` says whether Kit can nudge at all (the Firebase account is set up). See [[Phone App#He's with you]] |
| `POST /api/nudge` | A test nudge to every device with a push token (`kit nudge`; Kit's token only): `{"enabled", "sent": {"phone": "sent"}}` |

The hello's answer is what the brain can do:

```json
{"api": 1, "kit": "0.1.0", "name": "Kit",
 "body": {"id": "phone", "kind": "phone", "online": true, ...},
 "features": {"chat": 2, "messages": 2, "life": 1, "life_events": 1, "bodies": 1,
              "pairing": 1, "voice_out": 1, "push": 1, "phone_context": 1, ...},
 "events": ["mood", "fidget", "react", "state", "look", "doing", "quiet", "dials", "pipe_up"],
 "face": {"character": "kit3d", "style": "model", "page": "/face/?app=phone"},
 "unknown_abilities": []}
```

A body uses only the features listed, at the version given. Features and
fields are only ever added; a change of meaning is a new version number. A
body should skip events and fields it doesn't know. See [[Phone App#Saying hello]].

## What he senses

| Method and path | What it does |
|---|---|
| `POST /api/pc/context`, `GET /api/pc/context` | The desk app's report on what's on the PC. With several PCs, Kit keeps one report each; `GET` names the PC Dan's on (`host`) and lists them all (`pcs`) |
| `POST /api/phone/context`, `GET /api/phone/context` | The phone's report, in words only: `{"place": "home" \| "out" \| "unknown", "since", "battery": 0-100, "charging"}` (the phone's own token, or Kit's as `phone`). The answer carries the `line` Kit sees; `GET` gives the latest report per phone. See [[Phone App#What the phone tells him]] |
| `POST /api/eyes/scene`, `GET /api/eyes/scene` | What the eyes see, in words |
| `POST /api/eyes/pause` | Switch the eyes off or on |
| `GET /api/eyes/faces`, `POST /api/eyes/faces`, `DELETE /api/eyes/faces/{name}` | The people his eyes know |

## Voice, face and status

| Method and path | What it does |
|---|---|
| `GET /api/speech` | Voice engine status: the engine set, the one he's `using`, why if he `fell_back`, and whether Turbo runs as a `cuda_graph` |
| `POST /api/speech/say` | One sentence as a WAV file, in his voice and mood |
| `GET /api/face` | The character sheet in use |
| `GET /api/face/presets` | Every character, and which one he is |
| `GET /face/` | The 3D face page, plus `/face/api/info`, `/face/api/version`, `/face/model/...` |
| `GET /api/status` | Version, models, spend, memory size, what the PC, the phone and the eyes last said |
| `GET /api/health` | Is he up (no token) |
| `GET /api/spend`, `GET /api/spend/summary?days=30` | Cloud spend, as a log or per day and model |

## Under the hood
- `src/kit/server.py`: every route.
- `src/kit/body_registry.py` and `src/kit/devices.py`: bodies saying hello, and paired devices.
- `src/kit/desk/client.py`: the desk app's side.
- `src/kit/eyes/link.py`: the eyes' side.
