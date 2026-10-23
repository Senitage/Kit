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

`kit token` shows it. A paired device, like a phone, uses a token of its own
instead (`kit pair`): it opens the same API except the routes marked **Kit's
own token only** below (changing settings, the faces his eyes know, listing
bodies and devices, pairing), which answer `403` to a device's token. `kit
devices forget` stops a device's token. See [[Phone App#Pairing]] and
[[Privacy#Tokens and secrets]].

The pages (`/`, `/settings`, `/memory`) and the 3D face (`/face/...`) load
without one: the pages ask for it, and the face is only a
cartoon. See [[Privacy#Tokens and secrets]].

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
| `tool` | He's running a tool: `tool` (its name) and `line` (the call, like `recall(query='tax returns')`) |
| `tool_calls` | A cloud model asked for tools without a word to say: the calls, with no words for the chat yet (the `reply` comes after the results) |
| `confirm` | He wants to do something that needs your yes first: `tool`, `line` (the call), `ask` (what he'll do, in words) and `preview` (the change itself, like a note's diff, or empty). Your next message answers it. See [[Tools and Packs#Asking first]] |
| `recalled`, `remembered`, `reading_note`, `looked_at_pc`, `looked_around` | What a tool or action did mid-answer |
| `note_changed` | He changed one of your notes: `note` (where it is in the vault) and `change` (what he did, in words). See [[Notes on the NAS#Changing a note]] |
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
| `PATCH /api/settings` | Change settings. Merges one level deep, so send a model profile whole; a model sent as `null` is taken out of the list. Kit's own token only |
| `GET /api/settings/history` | Earlier versions |
| `POST /api/settings/undo` | Go back one change. Kit's own token only |

## Memory and the register

| Method and path | What it does |
|---|---|
| `GET /api/memory/facts` | What he knows |
| `POST /api/memory/facts` | Teach him a fact |
| `PATCH /api/memory/facts/{id}` | Edit or pin a fact |
| `GET /api/memory/facts/{id}/history` | A fact's earlier versions |
| `DELETE /api/memory/facts/{id}` | Forget a fact |
| `GET /api/memory/search?q=...` | Search the way Kit does, your files included (a file hit's `meta` has its `root`, `rel` path and `page`) |
| `GET /api/memory/days` | Day summaries |
| `GET /api/tools` | Every pack (`name`, `card`, `enabled`, `always`, `words`) and its tools (`name`, `effect`, `asks_first`, `description`) |
| `POST /api/tools/run` | Run one tool by hand: `{"tool", "arguments", "yes"}`. `409` for a tool that changes something of yours unless `yes` is true; `404` for one Kit doesn't have. Answers `{"ok", "text", "private"}` (`kit tools run`) |
| `GET /api/files` | Your folders: each root's `path`, `reachable`, `private`, `ocr`, `max_mb`, `files`, `pieces`, `last_run` and `unreadable`; whether a sync is `running`; and the NAS `shares` offered as choices ([[Your Files]]) |
| `POST /api/files/roots` | Add a folder: `{"name", "path", "private", "ocr"}`. `400` if the path isn't a folder the server can read. Starts reading it |
| `PATCH /api/files/roots/{name}` | Change `private`, `ocr` or `max_mb`; a private change applies to what's indexed at once |
| `DELETE /api/files/roots/{name}` | Remove a folder; what was read from it leaves memory (`dropped` says how many pieces) |
| `POST /api/files/sync` | Look for new and changed files now: `{"root", "full"}` (both optional). `started` is false if a sync is already running |
| `GET /api/things` | The register of things |
| `GET /api/things/suggestions` | Names he suggested adding |
| `POST /api/things`, `PATCH /api/things/{id}` | Add or change a thing |
| `POST /api/things/{id}/confirm`, `/reject` | Accept or drop a suggestion |
| `GET /api/things/{id}/history`, `DELETE /api/things/{id}` | History, or forget it |

## His inner life

| Method and path | What it does |
|---|---|
| `GET /api/life` | Mood, feeling and why, drives, thoughts, what's coming up |
| `GET /api/life/events?after=N&wait=25` | Events for bodies, waiting up to `wait` seconds for a new one; `resync: true` when events after N are already gone, so re-read `/api/life` |
| `GET /api/life/notebook` | His notebook |
| `DELETE /api/life/notebook/{id}` | Forget a notebook entry |
| `POST /api/life/sheet/restore` | Give back an earlier self-sheet |
| `POST /api/life/quirks/retire`, `/restore` | Drop a quirk, or bring one back |
| `POST /api/life/think`, `/reflect`, `/poke` | A thought, tonight's look back, or a pipe-up, now |
| `POST /api/life/snooze` | Keep him quiet for `minutes` (0 lets him talk again) |

Bodies listen to `/api/life/events`: `mood`, `fidget`, `react`, `state`
(asleep or awake, with `why` when there is one), `look`, `doing`, `quiet`,
`dials`, `pipe_up`, `remembered` (a fact learned once a reply was out: `fact`,
`decision` of `new`, `same` or `update`, and `replaced`), `heard` (someone
talked to him out loud: read his reply from `/api/hearing/turns/{turn}`) and
`hush` (someone talked over him: stop his voice) and `desk_command` (open
something on the PC: `command`, `kind`, `args`, and `to`, the PC's desk id;
claim it before doing it) and `house` (he noticed something in the house:
`what`, like "the garage just opened, after dark", and `entity`; see
[[The House#Noticing]]) and `notes_tidy` (his Sunday look over your
notes: `lines`, what looked untidy; see
[[Notes on the NAS#The Sunday look-over]]). See
[[Bodies]]. The last 200 are kept, and `look` events (every couple of
seconds while someone's in view) the last few, apart, so they never push the
others out. A `quiet` event says why he's keeping quiet (`because`) and, while
his eyes see you busy, what his bubble should say (`bubble`). A `pipe_up`
carries the line (`reply`), the line as his voice says it with any sounds
(`voice`), whether to say it out loud (`aloud`: false when his eyes see
nobody there), and which body says it (`to`, a body id: the PC Dan's using,
else the device he last talked through). Other bodies only show the words.

## Kit's bodies and paired devices

| Method and path | What it does |
|---|---|
| `POST /api/bodies/hello` | A body says what it is and can do: `{"id", "kind", "name", "app", "abilities": ["screen", "speaker", ...], "faces"}`. A paired device is known by its device name |
| `GET /api/bodies` | The bodies heard from (online, last seen, last used) and the paired devices. Each PC running the desk app is one, `desk:` and its name. A body quiet for a day drops off the list. Kit's own token only |
| `POST /api/devices/pair` | Pair a device from the device: send `{"name": "phone", "kind": "phone"}` with Kit's own token, get back the device's token. Pairing a name again replaces its token |
| `DELETE /api/devices/{name}` | Unpair a device (Kit's token, or the device's own) |

The hello's answer is what the brain can do:

```json
{"api": 1, "kit": "0.1.0", "name": "Kit",
 "body": {"id": "phone", "kind": "phone", "online": true, ...},
 "features": {"chat": 2, "messages": 2, "life": 1, "life_events": 1, "bodies": 1,
              "pairing": 1, "voice_out": 1, ...},
 "events": ["mood", "fidget", "react", "state", "look", "doing", "quiet", "dials", "pipe_up",
            "remembered", "heard", "hush"],
 "face": {"character": "kit3d", "style": "model", "page": "/face/?app=phone"},
 "unknown_abilities": []}
```

A body uses only the features listed, at the version given. Features and
fields are only ever added; a change of meaning is a new version number. A
body should skip events and fields it doesn't know. See [[Phone App#Saying hello]].

## What he senses

| Method and path | What it does |
|---|---|
| `POST /api/pc/context`, `GET /api/pc/context` | The desk app's report on what's on the PC (hourly with `recent_files`, names and times). With several PCs, Kit keeps one report each; `GET` names the PC Dan's on (`host`) and lists them all (`pcs`) |
| `POST /api/desk/commands/{id}/claim` | The desk app taking a `desk_command` before doing it: what to do, or 410 when it's no longer wanted |
| `POST /api/desk/commands/{id}/done` | How it went: `ok` and `detail`, in words Kit can say |
| `POST /api/eyes/scene`, `GET /api/eyes/scene` | What the eyes see, in words |
| `POST /api/eyes/pause` | Switch the eyes off or on |
| `GET /api/eyes/faces`, `POST /api/eyes/faces`, `DELETE /api/eyes/faces/{name}` | The people his eyes know. Kit's own token only |
| `POST /api/hearing/report` | The ears checking in; the answer has the switch, `[hearing]`, the voices version and his voice engine |
| `POST /api/hearing/heard` | Something the ears heard, in words, tone, sound and whose voice; talk meant for him starts a reply (`turn`) |
| `GET /api/hearing/turns/{turn}` | His reply to something he heard, as it's made: the same events as `/api/chat` |
| `POST /api/hearing/hush` | Someone is talking over him: his voice stops |
| `GET /api/hearing`, `POST /api/hearing/pause` | Whether the ears are listening and what he last made of something (never the words); the switch |
| `GET /api/hearing/voices`, `POST /api/hearing/voices`, `DELETE /api/hearing/voices/{name}` | The people his ears know, by voice print. Kit's own token only |

## Voice, face and status

| Method and path | What it does |
|---|---|
| `GET /api/speech` | Voice engine status: the engine set, the one he's `using`, why if he `fell_back`, and whether Turbo runs as a `cuda_graph` |
| `POST /api/speech/say` | One sentence in his voice and mood, **sent in pieces as it's made**: 16-bit mono samples (`Content-Type: audio/L16; rate=24000`, no header), with `X-Sample-Rate`, `X-Synth-Ms` (time to the first piece) and `X-Engine`. With `Accept: audio/wav` or `?wav=1` the whole sentence comes as one WAV file instead, with `X-Audio-Ms` (older desks, tools). `generation` (optional) numbers the reply: once a higher number has been seen, a sentence from a lower one gets `410` instead of being made, and one under way is cut short. `503` with `Retry-After: 1` while the engine is still loading (it loads in the background), `409` when speech is off. `aloud: false` for a clip that won't be played in the room (the ears learning his voice); otherwise his ears are told how long he'll be talking. See [[Voice#How a sentence becomes sound]] |
| `GET /api/face` | The character sheet in use |
| `GET /api/face/presets` | Every character, and which one he is |
| `GET /face/` | The 3D face page, plus `/face/api/info`, `/face/api/version`, `/face/model/...` |
| `GET /api/status` | Version, models, spend (`cloud_month_aud`, `cloud_cap_aud`, where today's `prices` came from), memory size, what the PC, eyes and ears last said, and `tools` (the `packs` he has, `hops` allowed, the packs the last message `loaded`, the call `pending` your yes or null, the ten most `recent` calls) and `brief` (`enabled`, how it was `given` today or null, the `parts` gathered) and `google` (null without a Google account; else `connected`, `needs_reconnect`, the `account`, whether the sign-in covers `gmail` and `calendar`, and the last `error`) |
| `GET /api/health` | Is he up (no token) |
| `GET /api/spend`, `GET /api/spend/summary?days=30` | Cloud spend in Australian dollars (`month_aud`, `cap_aud`, `aud_per_usd`), as a log (each call with its `cost_usd` as billed, `cost_aud` at the day's rate, `cached_tokens`, `cache_write_tokens` and `searches`) or per day and model (`cost_aud`, `total_aud`, with each model's `cached_tokens`) |

## Under the hood
- `src/kit/server.py`: builds the app and runs the background loops.
- `src/kit/routes/`: every route, one file per part of Kit (`chat.py`, `memory.py`,
  `life.py`, `speech.py` and so on), sharing one `AppState` and the token checks
  in `src/kit/routes/state.py`.
- `src/kit/body_registry.py` and `src/kit/devices.py`: bodies saying hello, and paired devices.
- `src/kit/desk/client.py`: the desk app's side.
- `src/kit/eyes/link.py`: the eyes' side.
- `src/kit/hearing/run.py`: the ears' side.
