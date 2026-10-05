# Kit

Kit is a personal AI assistant with a personality. He talks, sees, and helps
around the PC, the Synology NAS and the Obsidian notes. He starts life as an
on-screen helper and later gets a body: a desk robot arm.

Kit is built in tested stages. The plan and each stage's test checklist are in
the [roadmap](https://claude.ai/code/artifact/bdf67b43-5085-4ef9-bb29-9517f2dfee91).

## Current stage: 0, foundations

Set up the server machine with [docs/stage-0-setup.md](docs/stage-0-setup.md),
then run `kit check` until every line passes.

```
kit init     # create Kit's data folder and a starter settings file
kit paths    # show where Kit keeps its files
kit check    # check this machine is ready (GPU, Ollama, Tailscale, NAS, Claude)
```

## How Kit is laid out

- **Code** lives in this repo (`src/kit`). It runs on Windows now and on Linux
  later, and CI tests both.
- **Everything Kit owns** (settings, secrets, memory, logs) lives in one data
  folder outside the repo: `C:\ProgramData\Kit` on Windows, `/var/lib/kit` on
  Linux, or wherever `KIT_DATA_DIR` points. Moving Kit is copying that folder.
- **Settings** are one TOML file in that folder, checked against a schema.
  Configurators such as home_app change them through Kit, never directly.

## Development

```
python -m venv .venv
.venv\Scripts\activate          # Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```
