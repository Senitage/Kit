# Kit

Kit is Dan's personal AI assistant. The plan and every stage's test checklist are
in the roadmap linked from README.md. Work one stage at a time. How Kit works is
in the docs vault: start at docs/Home.md.

## Rules for all code

- Cross-platform server code: the server runs on Ubuntu under WSL now and a
  dedicated Linux box later, and must still run on Windows.
  Use `pathlib`; never hard-code paths, drive letters or `/` vs `\`. Every
  location comes from settings or `kit.paths`.
- Windows-only code (window control, tray app, desktop input) belongs only in the
  desk app package, never in the server side.
- Kit's state lives only in its data folder (`kit.paths.KitPaths`). Nothing is
  written anywhere else, so moving Kit is a folder copy.
- Secrets never go in settings.toml or the repo. Read them through `kit.credentials`.
- Kit never depends on home_app. Configurators call Kit; Kit never calls them.
- Outside effects (commands, HTTP, file writes, API clients) are passed in so
  tests can use fakes. Tests must pass on Windows and Linux without a GPU, NAS,
  network or API key.
- NAS shares are read-only for Kit, except the Obsidian vault.
- Anything Kit should be able to recall (notes, files, projects, photos) goes
  into the knowledge index (`kit.knowledge.Index`) as a new source, so recall,
  search, the memory page and `kit eval memory` cover it. See
  docs/3 Deep Dives/Memory In Depth.md.
- Memory schema changes are new entries in `kit.memory.MIGRATIONS`, never edits
  to old ones.
- The Pod (Kit's first robot body) lives in `pod/`: the ESP32 program
  (Arduino), its printed parts (CadQuery) and a Windows network helper. It
  isn't part of the Python package and ruff skips it. Its Wi-Fi password and
  Kit's token go in `wifi_settings.h` and `kit_server.h`, which are gitignored;
  only the `.example.h` copies are committed. When Kit 2D's character sheet
  changes, rebuild `kit2d_sheet.h` with `pod/firmware/kit_pod_face/make_sheet.py`.

## Docs

- `docs/` is an Obsidian vault, read by people and by Claude. `docs/Home.md` is
  the front door and `docs/Kit Map.canvas` the map. Layers: `1 Meet Kit`,
  `2 How Kit Works` (one plain-words note per part of Kit), `3 Deep Dives`,
  `4 Guides` (setup, updating, each stage's test checklist), `5 Reference`
  (Commands, Settings Reference, API, Evals, Code Map, Glossary) and
  `6 About These Docs`. Conventions are in
  docs/6 About These Docs/How These Docs Work.md.
- Links are wiki-links by note name (`[[Memory]]`, `[[Memory#Finding things]]`).
  Note names are unique across the vault. Every note starts with `tags` (its
  layer plus `topic/...`), `aliases`, `summary` and, where it has neighbours,
  `related` properties. Pictures go in `docs/Assets/`, embedded as
  `![[name.png]]`. A section shown in two notes is embedded
  (`![[Note#Heading]]`), not copied. `docs/All Notes.base` lists every note.
- Every change updates the docs in the same PR: the part's How Kit Works note
  and deep dive, its guide or docs/4 Guides/Updating Kit.md (and
  docs/4 Guides/Running Kit.md if how to run it changes), Code Map for
  modules, Commands, Settings Reference, API and Evals for those, Where Kit Is
  Up To for PRs opened or merged, the Glossary for new words, and fresh
  pictures when how Kit looks changes. A new part of Kit gets a note from
  `docs/Templates/`, linked from Home, Kit Map.canvas and its neighbours; a
  new stage gets a guide.
- `tests/test_docs.py` checks links, headings, pictures and properties, and
  that every module, setting and `kit` command is in the docs.
- The repo is public. No real addresses, places, network details (IPs, host
  names, home paths) or names of Dan's family, friends or pets in docs,
  pictures, tests or examples. Use made-up ones: Richmond, NSW for a town,
  192.168.1.50 for the NAS.

## Commands

- `pytest -q`, `ruff check .`, `ruff format --check .`
