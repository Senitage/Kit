# Stage 2: Kit's desk app for Windows

The desk app puts Kit on your desk PC:

- **Tray icon.** Kit's Glow face sits in the taskbar tray. Click it to open the
  chat. Right-click it for the menu: Open chat, Show Kit's face, Share what I'm
  working on, What Kit remembers, Settings, Look, Quiet for an hour, Kit in the
  browser, Set up the Chrome extension, Check for updates, Quit Kit.
- **Face on the desktop.** Glow floats on top of your windows. Drag him anywhere
  and he stays there next time. Click him to open the chat beside him. His eyes
  follow the mouse, he acts out every reply, and when the chat is closed he says
  it in a little speech bubble. He goes grey when he can't reach the brain.
- **Chat.** It's the same conversation as the web chat page, with the same
  memory. Your messages are on the right in the accent colour and Kit's are on
  the left, as rounded bubbles. Kit's replies show markdown: bold, lists, code,
  tables and clickable links. New messages fade in. Three dots show while
  he's thinking. While you're at the bottom the chat follows the newest
  message; scroll up to read and it stays put, with a **Latest** button to jump
  back. Drag any edge or the bottom-right corner to resize, and Kit remembers
  the size. Enter sends, Shift+Enter starts a new line, and the box grows as
  you type. You can ask again before he's answered. **New chat** starts fresh,
  and ⚙ opens Kit's window.
- **Kit's window.** Open it from ⚙ in the chat or from the tray menu. It has
  five pages:
  - **Memory**: search what Kit knows the way he does, teach him something, and
    pin, edit or forget facts. It's the same memory as the browser's memory page.
  - **Kit's settings**: the brain's settings, the same as the browser's
    settings page, with Save and Undo.
  - **This PC**: the brain's address and token, what Kit may see, and start at
    logon.
  - **Look**: dark, light or match Windows; the accent colour; Kit's eye
    colour; face size; text size; and whether he talks in a speech bubble.
    Changes show straight away.
  - **Updates**: the version you have, and new versions from GitHub (see
    [desk-app/README.md](desk-app/README.md)).
- **What you're working on.** Every couple of seconds the app checks which
  windows are open, which one has focus, and how long it's been since you
  touched the keyboard or mouse. It tells the brain when focus changes, and at
  least every 20 seconds otherwise. It reads window titles and app names only:
  no screenshots and no image processing.
- **PC health.** CPU, memory, free disk space, battery, network, uptime and the
  busiest apps.
- **Chrome extension.** Kit's own extension tells the desk app which tabs are
  open in Chrome (or Edge) and which one you're looking at, so Kit knows the
  site and address, not just the page title. See "The Chrome extension" below.

Kit sees one line about your PC on every message, for example *On Dan's PC
right now: VS Code: "pumps.py - METTOOLS", for 25 min. Also open: Excel,
Chrome.* When that isn't enough ("what have I been doing this morning?", "why
is my PC slow?"), he looks at the full picture: every open window, what had
focus in the last hour, time per app today, and PC health. The chat shows
"looking at your PC" while he does.

## Where you're talking from

Every message tells Kit which way it came in, and he's told on each turn:

| From | Kit is told | So he |
|---|---|---|
| Desk app | you're typing at your PC | takes "this" to mean what's on screen |
| Chat page on a phone (over Tailscale) | you're on your phone, probably out | keeps it short and doesn't assume you can see the PC |
| Chat page on a computer | you're on the chat page | answers as usual |
| Voice at the desk (stage 3) | you're talking out loud at the desk | keeps it short and spoken |
| `kit chat` | you're in the terminal | answers as usual |

Each message is stored with where it came from, so a message from earlier
shows as "(from their phone) ..." when you pick the conversation up at the
desk. It's one conversation and one memory whichever way you talk. With the PC
line beside it, Kit can also tell when you're on your phone but your PC is
busy, or locked and idle.

## The Chrome extension

The extension sends every open tab's title and address, and which tab you're
looking at, to the desk app whenever tabs change, and every 30 seconds. It
never reads what's on a page, and it skips incognito windows. It only talks to
the desk app on this PC (`127.0.0.1:8765`), never to the internet, and the desk
app only accepts Kit's own extension, so a website can't feed it fake tabs.

With it, the line Kit sees reads *Chrome: "Pump sizing - MetTools"
(mettools.lan), for 12 min*. When Kit looks at the full picture, he also sees
every tab (marking the ones showing and any playing sound) and the time spent
per website today.

**Add it** (once per browser):
1. Right-click Kit in the tray and choose **Set up the Chrome extension...**. It
   opens the extension's folder (`chrome-extension` beside Kit.exe).
2. In Chrome, go to `chrome://extensions` (in Edge, `edge://extensions`), turn
   on **Developer mode**, choose **Load unpacked** and pick that folder.
3. Pin Kit's icon if you like. Clicking it shows "Connected. Kit can see your
   tabs."

It isn't on the Chrome Web Store, which is why it goes in through Developer
mode. Chrome may remind you about developer-mode extensions now and then; keep
it. After a Kit update, press the reload arrow on Kit's card in
`chrome://extensions` to pick up the new version.

## Privacy

- Titles from password managers (KeePass, 1Password, Bitwarden and others), and
  titles containing words like bank, NetBank, PayPal, password, InPrivate or
  incognito, are blanked **on the PC** before anything is sent. Kit only learns
  that the app is open. Edit both lists in Settings.
- Addresses lose everything after `?` or `#` (search terms, session ids and
  tokens live there) before they leave the PC. A tab whose title or address
  contains a hidden word is blanked, address and all; Kit only sees that a
  hidden tab is open.
- Untick **Share what I'm working on** in the tray menu to pause. Kit is told
  it's paused and sees no windows at all. A locked PC shares nothing either.
- Today's activity is held in the brain's working memory only. It isn't saved
  to disk or to Kit's long-term memory yet, and it's gone when the brain
  restarts.
- When a cloud model answers, the one-line summary goes with the question, the
  same as the rest of the prompt. Add words to the hide list for anything you
  never want sent.

## Install

1. On GitHub, open **Releases** on the repo's front page and download
   `Kit-Desk-Setup-<version>.exe` from the latest one. Releases appear once
   the desk app is on `main`. Until then, or to try a pull request, open
   **Actions > Desk app**, pick the run, and download **Kit-Desk-Setup** under
   Artifacts (a zip with the exe inside). After the first install, Kit updates
   himself (see [desk-app/README.md](desk-app/README.md)).
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

The desk app only connects out to the brain. The one thing it listens on is
127.0.0.1:8765 for the Chrome extension, which nothing off the PC can reach, so
Windows won't ask about the firewall and no ports need opening.
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
- [ ] Add the Chrome extension. Its popup says it's connected. With a MetTools
      page in front, Kit's `/api/status` `pc` line names the site, and
      "what tabs have I got open?" lists them.
- [ ] Open NetBank in a tab. It shows as a hidden tab, with no title or address.
- [ ] Close Chrome. Within about 90 seconds Kit stops listing tabs.
- [ ] Untick Share what I'm working on. Kit says he can't see the screen. Tick
      it again and he can.
- [ ] Lock the PC (Win+L) for a minute. The activity shows as away, not as time
      in the last window.
- [ ] Ask "is my PC struggling?". The answer uses real CPU, memory and disk
      numbers.
- [ ] Log off and on again. Kit starts by himself, quietly in the tray.
- [ ] Run the installer again (an upgrade). It closes the running Kit, and Kit
      keeps his settings.
- [ ] Ask something with a list or a link. It shows formatted, and the link
      opens in the browser.
- [ ] Scroll up during a long reply. The chat stays where you are and shows
      **Latest**. Press it, and the chat follows new messages again.
- [ ] Resize the chat, close and reopen it. It keeps the size.
- [ ] In Kit's window, Memory: teach Kit something. It shows in the list and on
      the browser's memory page. Pin it, then forget it.
- [ ] Kit's settings: change `life.chattiness` and save. The browser's settings
      page shows the new value. Undo puts it back.
- [ ] Look: pick another eye colour, accent and Light. The face, tray icon,
      chat and window change straight away, and stay that way after a restart.
- [ ] Updates: paste the GitHub token (desk-app/README.md) and press Check now.
      It says you're up to date, or offers the newer version. Installing closes
      Kit, and he comes back by himself on the new version.

## Building

On the desk PC, with Python 3.11+ and Inno Setup 6
(`winget install JRSoftware.InnoSetup`):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

It installs the desk extra and PyInstaller, draws `kit.ico` from the Glow face,
builds `Kit.exe` as one folder, runs `Kit.exe --selftest`, and packs the
installer into `packaging\windows\build\installer`. How the build, GitHub's
workflow, releases and updates fit together is in
[desk-app/README.md](desk-app/README.md).

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
- `kit.desk.browser`: the 127.0.0.1-only listener for the extension, which
  checks that requests come from Kit's extension ID, and address cleaning.
  The extension itself is in `kit/desk/browser_extension` (Manifest V3; its
  fixed `key` gives it the same ID everywhere).
- `kit.desk.client`: the brain's HTTP API (`/api/status`, `/api/chat`,
  `/api/messages`, `/api/pc/context`).
- `kit.pc_context` (brain side, cross-platform): keeps the latest report and
  today's focus history, writes the prompt line, and answers `look_at_pc`.

Next steps: fold the day's PC activity into Kit's day summaries so he
remembers what you worked on; add a global hotkey for the chat; then stage 4's
PC actions (open apps, files and URLs) over the same link.
