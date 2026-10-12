---
tags: [how-it-works, topic/desk-app]
aliases: [kit.desk, Tray app, Kit Desk]
summary: Kit's home on the Windows PC - his face on the desktop, the chat, Kit's window, what's on the PC, the Chrome extension, his voice, and updates from GitHub.
related: ["[[Stage 2 - Desk App]]", "[[Desk App Builds and Updates]]", "[[Bodies]]"]
---

# Desk app

> [!ABSTRACT] In short
> The desk app is Kit's first body. It puts his **face** on the desktop and
> in the tray, a **chat** window, and **Kit's window** with his mood, memory,
> settings and looks. It tells the brain **what's on the PC** (window titles,
> idle time, PC health; never screenshots) and plays his **voice**. It only
> connects out to the brain, and updates itself from GitHub.

## What you see

- **His face on the desktop**, floating on top, wherever you drag him. His
  eyes follow the mouse (or you, with his [[Eyes]] on), he acts out every
  reply, and he says it in a speech bubble under his face. He goes grey when
  he can't reach the brain. Click him for the chat.
- **The tray icon**: click for the chat; right-click for the menu: Open
  chat, Show Kit's face, the switches (Share what I'm working on, Let Kit see
  me, Share what's playing, Boop when Kit talks), How Kit's feeling, What Kit
  remembers, Settings, Look, Quiet for an hour, Kit in the browser, Set up the
  Chrome extension, Check for updates, Quit Kit.
- **The chat**: the same conversation as everywhere else. Replies stream in
  as rounded bubbles with markdown, links and code. Copy a message or the
  whole chat. New chat starts fresh.
- **Kit's window**, with six pages:

| Page | What it's for |
|---|---|
| Mood | How he is at a glance: face, mood, feeling and why, needs bars. Only looks |
| Memory | Search what he knows, teach him, pin, edit or forget |
| Kit's settings | The brain's settings, with Save and Undo |
| This PC | The brain's address and token, what Kit may see, start at logon |
| Look | Theme, accent colour, eye colour, face size, text size, speech bubble, how much he moves |
| Updates | Your version, new versions from GitHub |

![[desk-look-page.png]]

## What Kit learns from the PC

Every couple of seconds the app checks which windows are open, which one has
focus, and how long since the keyboard or mouse was touched, plus CPU,
memory, disk and battery. With **Kit's Chrome extension** it also knows your
open tabs and the site you're on. Kit sees one line on every message
("VS Code: pumps.py, for 25 min. Also open: Excel, Chrome.") and the full
picture when he needs it (`look_at_pc`).

With the desk app on **several PCs**, Kit keeps each PC's report and follows
the one you're using; a locked laptop in the other room doesn't make him
think you've gone. He counts you as away only once every PC is locked or
idle. When he pipes up, only the PC you're on (or last used) says it out
loud; the others show the words.

Password managers, banking and private-browsing titles are blanked **on the
PC** before anything is sent, addresses lose everything after `?` or `#`, and
**Share what I'm working on** pauses it all. See [[Privacy]].

## His voice and face on the desk

- **Voice**: the app plays each sentence as soon as the server has made it,
  through one steady sound output, with any sound (a chuckle) in its place.
  His face talks for exactly as long as each sentence plays. See [[Voice]].
- **His bubble** shows what he's said, what he's up to while you're out, or,
  while his eyes see you on your phone, that he's keeping quiet.
- **Kit 3D**: when his character has a 3D look, the app lays the brain's face
  page over his window and mirrors every expression to it. See [[Face]].
- **Reflexes**: the only things the desk decides itself. Every so often he
  glances at the window you're working in. When the brain says he's asleep,
  he yawns and slides down the screen; awake, he climbs back.

## Connections

The app only ever connects **out** to the brain (`http://kit-server:8600`
over Tailscale, with the token from `kit token`). The **This PC** page shows
both, and **Copy** puts the token on the clipboard, for pairing the
[[Phone App]]. The one thing it listens on
is `127.0.0.1:8765`, for the Chrome extension, which nothing off the PC can
reach. Its own few settings and the token live in `%APPDATA%\Kit Desk`.

It connects over IPv4, which is what the brain listens on. Windows tries a
name's IPv6 address first (`localhost` gives `::1`) and waits about 2 s for an
answer that never comes, which made his voice start 2 s late on every reply.
Kit's eyes use the same connection.

## Updates

Every change merged into `main` is built into an installer by GitHub and
published as a release. About a minute and a half after start, then daily,
the app checks for a newer one, and installs it when you say so. A pull
request's build is a **test build**, which is only offered a release that
contains its changes. See [[Desk App Builds and Updates]].

## Go deeper
- [[Stage 2 - Desk App]]: install, the Chrome extension, privacy and the test checklist.
- [[Desk App Builds and Updates]]: how the installer is built, published and updated.
- [[Bodies]]: the desk app as one of Kit's bodies.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/desk/app.py`: the tray, the face window, the threads that talk to the brain.
> - `src/kit/desk/chat.py`, `src/kit/desk/window.py`, `src/kit/desk/mood.py`: the chat and Kit's window.
> - `src/kit/desk/watch.py`, `src/kit/desk/browser.py`: what's on the PC, and the extension's listener.
> - `src/kit/desk/glow.py`, `src/kit/desk/face3d.py`, `src/kit/desk/scenes.py`, `src/kit/desk/alive.py`: his face and body.
> - `src/kit/desk/voice.py`, `src/kit/desk/sound.py`: his voice and the boop.
> - `src/kit/desk/update.py`: updates. `packaging/windows/`: the installer recipe.
> - `src/kit/pc_context.py`: the brain's side of the PC feed.
