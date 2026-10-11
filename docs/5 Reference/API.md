---
tags: [reference, topic/api]
aliases: [HTTP API, Endpoints, Kit's API, Routes]
summary: Every web address the brain answers on - chat, settings, memory, the register, life events, the PC, eyes and ears feeds, speech, spend and the 3D face - and how the token works.
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

`kit token` shows it. The pages (`/`, `/settings`, `/memory`) and the 3D face
(`/face/...`) load without one: the pages ask for it, and the face is only a
cartoon. See [[Privacy#Tokens and secrets]].

## Talking

| Method and path | What it does |
|---|---|
| `POST /api/chat` | Send `{"text": ..., "channel": "desk"}`. The answer streams back as one JSON event per line (below) |
| `POST /api/chat/new` | Start a fresh conversation |
| `GET /api/messages?limit=50` | Recent messages, with their replies |

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
(asleep or awake, with `why` when there is one), `look`, `doing`, `quiet`,
`dials`, `pipe_up`, `heard` (someone talked to him out loud: read his reply
from `/api/hearing/turns/{turn}`) and `hush` (someone talked over him: stop
his voice). See [[Bodies]]. A `quiet` event says why he's keeping quiet
(`because`) and, while his eyes see you busy, what his bubble should say
(`bubble`). A `pipe_up` carries the line (`reply`), the line as his voice says
it with any sounds (`voice`), and whether to say it out loud (`aloud`: false
when his eyes see nobody there).

## What he senses

| Method and path | What it does |
|---|---|
| `POST /api/pc/context`, `GET /api/pc/context` | The desk app's report on what's on the PC |
| `POST /api/eyes/scene`, `GET /api/eyes/scene` | What the eyes see, in words |
| `POST /api/eyes/pause` | Switch the eyes off or on |
| `GET /api/eyes/faces`, `POST /api/eyes/faces`, `DELETE /api/eyes/faces/{name}` | The people his eyes know |
| `POST /api/hearing/report` | The ears checking in; the answer has the switch, `[hearing]`, the voices version and his voice engine |
| `POST /api/hearing/heard` | Something the ears heard, in words, tone, sound and whose voice; talk meant for him starts a reply (`turn`) |
| `GET /api/hearing/turns/{turn}` | His reply to something he heard, as it's made: the same events as `/api/chat` |
| `POST /api/hearing/hush` | Someone is talking over him: his voice stops |
| `GET /api/hearing`, `POST /api/hearing/pause` | Whether the ears are listening and what he last made of something (never the words); the switch |
| `GET /api/hearing/voices`, `POST /api/hearing/voices`, `DELETE /api/hearing/voices/{name}` | The people his ears know, by voice print |

## Voice, face and status

| Method and path | What it does |
|---|---|
| `GET /api/speech` | Voice engine status: the engine set, the one he's `using`, and why if he `fell_back` |
| `POST /api/speech/say` | One sentence as a WAV file, in his voice and mood (`aloud: false` for a clip that won't be played in the room) |
| `GET /api/face` | The character sheet in use |
| `GET /api/face/presets` | Every character, and which one he is |
| `GET /face/` | The 3D face page, plus `/face/api/info`, `/face/api/version`, `/face/model/...` |
| `GET /api/status` | Version, models, spend, memory size, what the PC, eyes and ears last said |
| `GET /api/health` | Is he up (no token) |
| `GET /api/spend`, `GET /api/spend/summary?days=30` | Cloud spend, as a log or per day and model |

## Under the hood
- `src/kit/server.py`: every route.
- `src/kit/desk/client.py`: the desk app's side.
- `src/kit/eyes/link.py`: the eyes' side.
- `src/kit/hearing/run.py`: the ears' side.
