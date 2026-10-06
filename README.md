# Kit

Kit is a personal AI assistant with a personality. He talks, sees, and helps
around the PC, the Synology NAS and the Obsidian notes. He starts life as an
on-screen helper and later gets a body: a desk robot arm.

Kit is built in tested stages. The plan and each stage's test checklist are in
the [roadmap](https://claude.ai/code/artifact/bdf67b43-5085-4ef9-bb29-9517f2dfee91).

## Current stage: 1, text brain

Kit chats by text in a browser or terminal. It recalls what's relevant from
everything it has learned, by words and by meaning, and keeps its facts tidy
as things change ([how memory works](docs/memory.md)). A register of things
(people, vehicles, places, projects, equipment) tells it where each one lives:
which NAS folder, Obsidian note, home_app record or Home Assistant area. Small talk stays on the
local model; real questions go to a cloud model (Claude, GPT or Gemini, your
choice) with web search, within a monthly budget. How much stays local is a
setting. It has settings and memory pages with history and undo. Set it up and test it with
[docs/stage-1-text-brain.md](docs/stage-1-text-brain.md).

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

Stage 0 ([docs/stage-0-setup.md](docs/stage-0-setup.md)) set up the server;
`kit init`, `kit paths` and `kit check` are still there.

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
