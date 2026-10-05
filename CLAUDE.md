# Kit

Kit is Dan's personal AI assistant. The plan and every stage's test checklist are
in the roadmap linked from README.md. Work one stage at a time.

## Rules for all code

- Cross-platform server code: it runs on Windows now and moves to Linux later.
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

## Commands

- `pytest -q`, `ruff check .`, `ruff format --check .`
