# Kit

Kit is a personal AI assistant with a personality. He talks, sees, and helps
around the PC, the Synology NAS and the Obsidian notes. He starts life as an
on-screen helper and later gets a body: a desk robot arm.

Kit is built in tested stages. The plan and each stage's test checklist are in
the [roadmap](https://claude.ai/code/artifact/bdf67b43-5085-4ef9-bb29-9517f2dfee91).

## Where Kit is up to (9 October 2026)

| Part | State | Pull requests |
| --- | --- | --- |
| Stage 0: setup and `kit check` | Passed | #1 |
| Stage 1: text brain and memory | Passed | #2 |
| Stage 2: desk app and Glow face | Passed, redesign and self-updates merged | #3, #4, #5 |
| Inner life: feelings, notebook, nightly reflection | Merged | #6 |
| Notes in the NAS vault, only when asked | Merged | #7, #8, #10 |
| Companion stage 1: he knows you were gone | Merged | #12 |
| Companion stage 2: he follows your life | Merged | #13, #14 |
| Cloud-only routing (Haiku chats, Sonnet works, ask before Opus) | Merged | #15 |
| Stage 3 part 1: Kit's voice | Built and being tested, not merged | #9 (draft) |
| Vision stage 1: Kit sees you | Built, waiting on a test with the webcam | #11 |

Next up: companion stages 3 to 5, then land the voice (#9) and vision (#11),
then the microphone (stage 3 part 2) and stage 4 (tools, PC control and the
Claude Code bridge). The full list and the decisions still open are at the top
of the roadmap.

## Stage 1: text brain

Kit chats by text in a browser or terminal. It recalls what's relevant from
everything it has learned, by words and by meaning, and keeps its facts tidy
as things change ([how memory works](docs/memory.md)). A register of things
(people, vehicles, places, projects, equipment) tells it where each one lives:
which NAS folder, Obsidian note, home_app record or Home Assistant area. Real
questions go to a cloud model (Claude, GPT or Gemini, your choice) with web
search, within a monthly budget. How much stays local is a setting
(`routing.mode`): `balanced` keeps small talk on the local model, and
`cloud-only` has a cheap chat model (Haiku) answer everything, hand real work
to Sonnet and ask before calling Opus. It has settings and memory pages with history and undo. Set it up and test it with
[docs/stage-1-text-brain.md](docs/stage-1-text-brain.md). Ideas waiting for a later stage are in
[docs/improvements.md](docs/improvements.md).

```
kit serve          # run Kit: chat at /, memory at /memory, settings at /settings
kit chat           # talk to Kit in the terminal
kit config ...     # show, set, undo or check settings without a browser
kit models         # which models do what; `kit models work gpt-sol` switches
kit memory ...     # see, search, teach, pin or forget what Kit knows; cloud spend
kit eval           # 50 prompts: are replies valid, and how fast do words start?
kit things ...     # the register of things and where each one lives
kit eval memory    # does Kit recall the right facts and keep its memory tidy?
kit eval routing   # do questions bring back the right thing and where it lives?
kit eval compare --models sonnet gpt-sol   # same questions, side by side
kit token          # the API token for the pages and home_app
```

Kit reads your Obsidian notes vault on the NAS and takes notes in it when you ask:
set it up with [docs/notes.md](docs/notes.md).

Stage 0 ([docs/stage-0-setup.md](docs/stage-0-setup.md)) set up the server;
`kit init`, `kit paths` and `kit check` are still there.

## Stage 2: the desk app

`Kit-Desk-Setup.exe` puts Kit on the Windows desk PC: his Glow face in the tray
and floating on the desktop, a chat window, and a feed of which windows are
open and what has focus (titles only, no screenshots), plus PC health. A Chrome
extension adds the open tabs and the site you're on. Install
and test it with [docs/stage-2-desk-app.md](docs/stage-2-desk-app.md).
How the installer is built and published, and how the app updates itself:
[docs/desk-app/README.md](docs/desk-app/README.md).

## Kit as a companion, stage 2

He follows your life. Mention something coming up ("dentist Thursday arvo") and
he asks how it went once it's over; ask him to check in after your 2 pm and he
does. A new chat picks up one thing from the last, Monday brings "how was the
weekend?", and each night he writes what's going on with you so he never asks
what he already knows. He gets to know you a question a day, nudges you to bed
or outside once a day, keeps running jokes, and Claude steps in for the moments
that matter. Update and test it with
[docs/stage-companion-2.md](docs/stage-companion-2.md).

```
kit life             # now also: what he'll ask about and when
kit life notebook    # what's going on with you, threads, running jokes
```

## Kit as a companion, stage 1

Kit knows how long you were gone, even across a restart. He's glad when you're
back and says hello once (asking how lunch was, if you said), sees you off with
one warm line and no guilt, and after his first week is a bit miffed if you
vanish for hours without a goodbye. He's a small companion on your side rather
than an assistant: an honest friend who corrects you kindly and asks one
question at a time. He knows what's true about himself, grows closer to you
slowly, suggests a small game now and then, and reacts the moment you speak.
Update and test it with [docs/stage-companion-1.md](docs/stage-companion-1.md).

```
kit life                                  # now also: how close you are, a hello owed, your last goodbye
kit eval companion --models gemma4:e4b    # clean goodbyes, no guilt in hellos, honest answers
```

## Kit's inner life (side stage)

Kit gets a life between conversations: feelings with a reason, private thoughts
while you work, things he wants to bring up (including "ask me tomorrow..."),
and a notebook with his journal and a self-sheet he rewrites each night, so he
grows a little each day. A weekly review shows how he's changed, and you can
undo any of it on the memory page. How it works is in [docs/life.md](docs/life.md);
update, pick his voice and test it with
[docs/stage-inner-life.md](docs/stage-inner-life.md).

```
kit life             # how he feels and why, what he's thinking, what he wants to bring up
kit life think       # have a thought now
kit life reflect     # look back on today so far (a few cents)
kit life notebook    # his self-sheet, quirks, thoughts, opinions and journal
kit eval voice --models qwen3:8b gemma4:e4b   # which local model sounds most alive?
```

## How Kit is laid out

- **Code** lives in this repo (`src/kit`). The server runs on Linux: Ubuntu under
  WSL on the GPU PC now, a dedicated Linux box later. The desk app runs on
  Windows, so CI tests both.
- **Everything Kit owns** (settings, secrets, memory, logs) lives in one data
  folder outside the repo: `/var/lib/kit` on Linux, `C:\ProgramData\Kit` on
  Windows, or wherever `KIT_DATA_DIR` points. Moving Kit is copying that folder.
- **Settings** are one TOML file in that folder, checked against a schema.
  Configurators (the built-in page, `kit config`, later home_app) change them
  through Kit's API, which keeps every earlier version for undo. Kit never
  calls a configurator, so it runs fine without them.

## Development

```
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```
