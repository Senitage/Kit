# Kit

Kit is a personal AI assistant with a personality. He talks, sees, and helps
around the PC, the Synology NAS and the Obsidian notes. He starts life as an
on-screen helper and later gets a body: a desk robot arm.

Kit is built in tested stages. The plan and each stage's test checklist are in
the [roadmap](https://claude.ai/code/artifact/bdf67b43-5085-4ef9-bb29-9517f2dfee91).

## Current stage: 1, text brain

Kit chats by text in a browser or terminal, remembers you across restarts,
hands hard questions to Claude within a monthly budget, and has a settings
page with history and undo. Set it up and test it with
[docs/stage-1-text-brain.md](docs/stage-1-text-brain.md).

```
kit serve          # run Kit: chat page at /, settings page at /settings
kit chat           # talk to Kit in the terminal
kit config ...     # show, set, undo or check settings without a browser
kit memory ...     # facts Kit remembers, and this month's Claude spend
kit eval           # 50 prompts: are replies valid, and how fast do words start?
kit token          # the API token for the pages and home_app
```

Stage 0 ([docs/stage-0-setup.md](docs/stage-0-setup.md)) set up the server;
`kit init`, `kit paths` and `kit check` are still there.

## How Kit is laid out

- **Code** lives in this repo (`src/kit`). It runs on Windows now and on Linux
  later, and CI tests both.
- **Everything Kit owns** (settings, secrets, memory, logs) lives in one data
  folder outside the repo: `C:\ProgramData\Kit` on Windows, `/var/lib/kit` on
  Linux, or wherever `KIT_DATA_DIR` points. Moving Kit is copying that folder.
- **Settings** are one TOML file in that folder, checked against a schema.
  Configurators (the built-in page, `kit config`, later home_app) change them
  through Kit's API, which keeps every earlier version for undo. Kit never
  calls a configurator, so it runs fine without them.

## Development

```
python -m venv .venv
.venv\Scripts\activate          # Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```
