# Stage 2: Kit's desk app for Windows

The desk app puts Kit on your desk PC:

- **Tray icon.** Kit's Glow face sits in the taskbar tray. Click it to open the
  chat. Right-click it for the menu: Open chat, Show Kit's face, Share what I'm
  working on, Kit in the browser, What Kit remembers, Settings, Quit Kit.
- **Face on the desktop.** Glow floats on top of your windows. Drag him anywhere
  and he stays there next time. Click him to open the chat beside him. His eyes
  follow the mouse, he acts out every reply, and when the chat is closed he says
  it in a little speech bubble. He goes grey when he can't reach the brain.
- **Chat.** It's the same conversation as the web chat page, with the same
  memory. Enter sends and Shift+Enter starts a new line. You can ask again
  before he's answered.
- **What you're working on.** Every couple of seconds the app checks which
  windows are open, which one has focus, and how long it's been since you
  touched the keyboard or mouse. It tells the brain when focus changes, and at
  least every 20 seconds otherwise. It reads window titles and app names only:
  no screenshots and no image processing.
- **PC health.** CPU, memory, free disk space, battery, network, uptime and the
  busiest apps.

Kit sees one line about your PC on every message, for example *On Dan's PC
right now: VS Code: "pumps.py - METTOOLS", for 25 min. Also open: Excel,
Chrome.* When that isn't enough ("what have I been doing this morning?", "why
is my PC slow?"), he looks at the full picture: every open window, what had
focus in the last hour, time per app today, and PC health. The chat shows
"looking at your PC" while he does.

## Privacy

- Titles from password managers (KeePass, 1Password, Bitwarden and others), and
  titles containing words like bank, NetBank, PayPal, password, InPrivate or
  incognito, are blanked **on the PC** before anything is sent. Kit only learns
  that the app is open. Edit both lists in Settings.
- Untick **Share what I'm working on** in the tray menu to pause. Kit is told
  it's paused and sees no windows at all. A locked PC shares nothing either.
- Today's activity is held in the brain's working memory only. It isn't saved
  to disk or to Kit's long-term memory yet, and it's gone when the brain
  restarts.
- When a cloud model answers, the one-line summary goes with the question, the
  same as the rest of the prompt. Add words to the hide list for anything you
  never want sent.

## Install

1. On GitHub, open **Actions > Desk app**, pick the latest run on this branch,
   and download **Kit-Desk-Setup** under Artifacts. Unzip it to get
   `Kit-Desk-Setup-<version>.exe`. To build it yourself instead, see Building
   below.
2. Run it. It installs for your account only, so no admin prompt appears. Leave
   **Start Kit when I log on** ticked. Windows SmartScreen may warn about an
   unknown publisher, because the exe isn't code-signed: choose More info >
   Run anyway.
3. On first run, Kit asks for:
   - **Kit's address:** `http://kit-server:8600`, the same address you use for
     the web chat over Tailscale (stage 0 section 5, stage 1 "open it from your
     desk PC"). The brain must be listening beyond localhost
     (`kit config set brain.host 0.0.0.0`, then restart Kit).
   - **Token:** run `kit token` on the server and paste it.

   Press **Test connection**. It should say "Connected to Kit". Save.

The desk app only connects out to the brain. Nothing on the desk PC listens on
the network, so Windows won't ask about the firewall and no ports need opening.
Stage 4 PC control reuses the same outgoing link.

Settings and the token live in `%APPDATA%\Kit Desk` (`desk.toml` and
`api_token`), along with `desk.log`. Uninstalling keeps them, so a reinstall
reconnects without asking.

## Test checklist

- [ ] The installer runs without admin rights. Kit appears in the tray, and Glow
      appears in the bottom right of the screen.
- [ ] Test connection succeeds. With the brain stopped, the face and tray icon
      go grey within about 15 seconds, then come back when it restarts.
- [ ] Clicking the tray icon or the face opens the chat beside the face. Recent
      conversation from the web chat is shown.
- [ ] Ask "hi". The words stream in, the face plays the emotion and gesture, and
      with the chat closed the speech bubble shows the words.
- [ ] Drag the face to another spot, quit Kit and start it again. The face comes
      back where you left it.
- [ ] With VS Code focused for a few minutes, ask "what am I working on?". Kit
      names the app and file. `GET /api/pc/context` (or `/api/status`, the
      `pc` line) shows the same.
- [ ] Ask "what have I been doing for the last hour?". The chat shows "looking
      at your PC", and the answer covers the apps you actually used.
- [ ] Open your bank's website. Neither the line in `/api/status` nor the
      `/api/pc/context` detail shows its title.
- [ ] Untick Share what I'm working on. Kit says he can't see the screen. Tick
      it again and he can.
- [ ] Lock the PC (Win+L) for a minute. The activity shows as away, not as time
      in the last window.
- [ ] Ask "is my PC struggling?". The answer uses real CPU, memory and disk
      numbers.
- [ ] Log off and on again. Kit starts by himself, quietly in the tray.
- [ ] Run the installer again (an upgrade). It closes the running Kit, and Kit
      keeps his settings.

## Building

On the desk PC, with Python 3.11+ and Inno Setup 6
(`winget install JRSoftware.InnoSetup`):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

It installs the desk extra and PyInstaller, draws `kit.ico` from the Glow face,
builds `Kit.exe` as one folder, runs `Kit.exe --selftest`, and packs the
installer into `packaging\windows\build\installer`.

To run from source without installing: `pip install -e ".[desk]"`, then
`kit-desk` (or `python -m kit.desk`). It also runs on Linux for trying out the
face and chat; there it reports PC health but no windows.

## How it fits together

- `kit.desk.app`: the tray, the face window, the speech bubble, settings, and
  the threads that talk to the brain.
- `kit.desk.chat`: the chat window. Brain calls run on worker threads and come
  back through Qt signals.
- `kit.desk.watch`: `WindowsDesktop` (Win32 through ctypes: windows, focus, idle
  time, lock screen), `system_status` (psutil), the privacy filter, and
  `Reporter`, which decides when to send.
- `kit.desk.client`: the brain's HTTP API (`/api/status`, `/api/chat`,
  `/api/messages`, `/api/pc/context`).
- `kit.pc_context` (brain side, cross-platform): keeps the latest report and
  today's focus history, writes the prompt line, and answers `look_at_pc`.

Next steps: fold the day's PC activity into Kit's day summaries so he
remembers what you worked on; add a global hotkey for the chat; then stage 4's
PC actions (open apps, files and URLs) over the same link.
