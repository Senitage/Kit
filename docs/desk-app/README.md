# Kit's desk app: how it's built, published and updated

The desk app is Kit's body on the Windows desk PC: the tray icon, the Glow face,
the chat, Kit's window (memory, settings, look, updates) and the feed of what
you're working on. What it does and how to test it is in
[../stage-2-desk-app.md](../stage-2-desk-app.md). This page covers where it
lives in the repo, how GitHub turns it into an installer, and how updates reach
your PC.

## Where it lives

| Path | What it is |
|---|---|
| `src/kit/desk/` | The app itself, all Python (PySide6 for the windows). `app.py` starts it. |
| `src/kit/desk/chat.py` | The chat window. |
| `src/kit/desk/window.py` | Kit's window: Mood, Memory, Kit's settings, This PC, Look, Updates. |
| `src/kit/desk/mood.py` | The Mood page: his face, mood gem and needs bars, read from the brain. |
| `src/kit/desk/scenes.py` | What Glow shows when the brain sends a show: the time, the date, the weather. |
| `src/kit/desk/sound.py` | The boop when he says something. |
| `src/kit/desk/theme.py` | Colours and styles, from the Look page. |
| `src/kit/desk/update.py` | The update check and download. |
| `src/kit/desk/browser_extension/` | The Chrome extension. |
| `packaging/windows/kit_desk.py` | The tiny start-up file PyInstaller freezes. |
| `packaging/windows/build.ps1` | The build recipe (below). |
| `packaging/windows/kit-desk.iss` | The installer recipe (Inno Setup). |
| `.github/workflows/desk-app.yml` | Tells GitHub to run the recipe on every change. |
| `tests/test_desk_*.py` | The desk app's tests. They run without a screen. |

No `.exe` is stored in the repo. The repo holds the recipe, and the exe is
cooked from it each time.

## How the exe is made

`packaging/windows/build.ps1` does four things:

1. **Numbers the build.** On GitHub it writes the run number into
   `src/kit/desk/_build.py`, so the version reads `0.1.0.<run number>`, for
   example `0.1.0.57`. Each build is newer than the one before, which is how
   the update check spots a new one. A build made by hand is `0.1.0.0`.
2. **Freezes the app with PyInstaller.** PyInstaller collects Python itself, Kit's
   desk code, Qt and every library into a folder with `Kit.exe` in it, so the
   desk PC doesn't need Python installed.
3. **Self-tests it.** It runs `Kit.exe --selftest`, which opens the chat and
   Kit's window off-screen and exits. A broken exe stops the build here.
4. **Wraps it in an installer with Inno Setup.** That gives
   `Kit-Desk-Setup-<version>.exe`, which installs for your account only (no
   admin prompt), adds the Start menu entry, start-at-logon and the Chrome
   extension folder, and can uninstall cleanly.

You can run the same script on the desk PC with Python 3.11+ and Inno Setup 6:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

## What GitHub does with it

The **Desk app** workflow runs on a fresh Windows machine at GitHub for every
pull request and every change to `main`:

1. Installs Python and the desk app.
2. Runs the desk app tests against the real Windows API.
3. Runs `build.ps1`.
4. Attaches the installer to the run under **Artifacts**. GitHub always zips
   artifacts, which is why a run gives you a zip. These are for trying a pull
   request before it's merged.
5. **On `main` only, publishes a Release** tagged `desk-v<version>`, with the
   installer attached as a plain `.exe`. Find it under **Releases** on the
   repo's front page. The newest is marked *Latest*.

## Updates

Once Kit is installed you shouldn't need to download anything again:

- About a minute and a half after Kit starts, and then once a day, he asks
  GitHub for the newest `desk-v...` release. You can also press **Check now** on
  the Updates page, or use **Check for updates...** in the tray menu.
- When there's a newer version he says so in a Windows notification and opens
  the Updates page with the release notes. Nothing installs until you press
  **Download and install**.
- The installer is downloaded to `%APPDATA%\Kit Desk\updates` and checked
  against GitHub's size and SHA-256 checksum. A damaged download is thrown away.
- Kit then runs the installer quietly and closes. The installer replaces the
  files and starts Kit again, and your settings stay as they were.

Untick **Check for updates once a day** on the Updates page to stop the checks.

### The GitHub token (while the repo is private)

GitHub only shows a private repo's releases to someone signed in, so the desk
app needs a token that can read them. Make one once:

1. On github.com, open your picture > **Settings** > **Developer settings** >
   **Personal access tokens** > **Fine-grained tokens** > **Generate new token**.
2. Name it "Kit desk updates". Set an expiry (a year is fine).
3. Under **Repository access**, choose **Only select repositories** and pick
   **Kit**.
4. Under **Permissions** > **Repository permissions**, set **Contents** to
   **Read-only**. Leave everything else as it is.
5. Generate it, copy it, and paste it into **GitHub token** on Kit's Updates
   page.

The token can only read the Kit repo. It's stored in `%APPDATA%\Kit Desk\github_token`,
never in `desk.toml` or the repo. If the repo is ever made public, the token
isn't needed at all.

## Making a change to the desk app

1. Change the code under `src/kit/desk/` and run the tests:
   `pytest -q tests/test_desk_app.py tests/test_desk_update.py`.
2. Try it from source with `kit-desk` (or `python -m kit.desk`).
3. Open a pull request. The Desk app workflow builds an installer you can try
   from the run's Artifacts.
4. Merge it. GitHub publishes the release, and Kit on your desk offers it
   within a day.
