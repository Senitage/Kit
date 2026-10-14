---
tags: [how-it-works, topic/privacy]
aliases: [Keep it local, What Kit sees, The switches, Security]
summary: What Kit sees, what leaves the house and what never does - keep it local, the desk app's switches, the eyes' no-pictures rule, read-only shares, tokens and secrets.
related: ["[[Memory]]", "[[Stage 2 - Desk App]]", "[[Vision Stage 1]]", "[[Tools and Packs]]"]
---

# Privacy

> [!ABSTRACT] In short
> Kit lives at home: his brain, memory and voice run on your own server.
> Only the words a **cloud model** needs to answer leave the house, and
> **"keep it local"** stops even that for anything you choose. On the PC he
> sees **window titles, never screenshots**; through the camera he sees
> **words and numbers, never pictures**; through the mic he gets **words, never
> sound**. In **cloud-only** routing those words go to the cloud chat model,
> the full list when you ask about your PC or what he can see. Every way in has
> a **switch**, and you can see and forget anything he remembers.

## What stays home, and what goes out

| | Stays on your server | Goes to a cloud model |
|---|---|---|
| Memory, the notebook, the register | always | only the few memories recalled for that message |
| Your messages | always | when a cloud model answers them, unless kept local |
| What's on the PC, the scene from the eyes | always | the one-line summary with every message a cloud model answers; the full picture when it answers a question about your PC or the room, or decides to look (see below) |
| His voice | always (the engine runs on the server's GPU) | never |
| The camera | never leaves the PC as a picture | never |
| The microphone | never leaves the PC as sound; only words meant for Kit are kept | his words, when a cloud model answers them |
| Notes in your vault | always | the parts recalled for that message |

Which model answers is in [[Models and Routing]]. Turning `routing.mode` to
`local-heavy` keeps far more at home; the cloud is still there for what the
local model can't do.

## What a cloud model sees of your PC and the room

Plainly, because it's easy to assume less goes out than does:

- **Every message a cloud model answers** carries the **one-line summary**
  of the PC ("VS Code: pumps.py, for 25 min. Also open: Excel, Chrome.") and
  of what the eyes see ("one person at the desk, and the cat"), the same as
  the rest of the prompt.
- **A question about your PC or the room** ("what have I got open?", "can
  you see the cat?") is answered by Kit's own model with the **full picture**
  in the prompt: every open window's title, the browser's tabs, what's had
  focus this hour and today, today's websites, PC health; or who's at the desk
  by name, what they're doing or holding, what's in view and who's been in
  today. In `local-heavy`, `balanced` and `cloud-first` routing Kit's own
  model is the **local** one, so none of that leaves the house. In
  **`cloud-only`** routing Kit's own model is the **cloud chat model**
  (Haiku), so the full picture goes to it. That's a choice the owner made,
  with eyes open: in cloud-only mode the local model only stands in.
- **Any model answering, local or cloud, is offered the `look_at_pc` and
  `look_around` actions** when the desk app or the eyes are running. When a
  cloud model (chat, work or expert, in any mode) decides the summary isn't
  enough and looks, the full picture goes to that model as its next message.
- **"Keep it local" wins.** Say it with the question and the look, and the
  answer, stay on the local model whatever the routing mode.
- What the PC never shares in the first place (hidden apps and words, blanked
  addresses, a paused switch) isn't in the full picture either. The camera
  still never sends a picture: the full scene is words.

To keep every look at home, run `balanced` or `local-heavy` routing, or say
"keep it local". `routing.mode` is in [[Settings Reference#routing]].

## Keep it local

Say **"keep it local"** with a message and it's answered by the local model,
and everything that comes from it is marked private: what he learns, the day's
summary, a reminder, his thoughts about it, his journal. None of it ever goes
to a cloud model, in recall, reflection or review. The words are read once, as
the message arrives, and stored with it as a **private flag**; everything
after (the history a cloud model sees, recall, the threads he follows, what
he learns) reads the flag, not the words. Messages from before the flag
existed were marked from their words when the memory file was updated. A
test walks one kept-local message past every way into the cloud (the answer,
the fact check, learning, the next answers, a key moment, pipe-ups, his
thoughts, the day's summary and his reflection) and checks none of it is in
anything a cloud model is sent. See [[Memory In Depth#What you keep local]].

## The switches

| Switch | Where | What it stops |
|---|---|---|
| **Share what I'm working on** | desk app tray menu | window titles, tabs and idle time |
| **Let Kit see me** | tray menu, or `kit eyes pause` | the camera: it's released, and Kit is told he can't see |
| **Let Kit hear me** | tray menu, or `kit hearing pause` | the microphone: it's let go, and Kit is told he can't hear |
| **Share what's playing** | tray menu | the music the PC is playing |
| **Quiet for an hour** | tray menu | piping up |
| `life.enabled` and friends | settings | his inner life, games, nudges, questions |

## On the PC

- **Titles, never screenshots.** Password managers, banking and private
  browsing are blanked **on the PC**, before anything is sent. Web addresses
  lose everything after `?` or `#`.
- **The desk app only connects out**, to the brain. The one port it listens
  on is for the Chrome extension, on `127.0.0.1`, which nothing off the PC can
  reach. See [[Desk App#Connections]].

## The camera

The eyes send the brain **words and numbers**, never a picture or a video.
People are recognised from sets of numbers worked out from their face, from
which a face can't be rebuilt; `kit eyes forget NAME` deletes them. See
[[Eyes]].

## The microphone

The ears turn talking into words **on the PC with the mic**; no sound is sent
or saved. The brain keeps only what was meant for Kit (his name, or answering
him), as an ordinary message. Everything else is let go: not kept, not sent
on, not written in the log. (`kit hearing --words` shows the words in the
ears' own window while you tune them, and saves nothing.) Voices are recognised from voice prints, numbers
from which no sound can be rebuilt; `kit hearing forget NAME` deletes them.
See [[Hearing]].

## Your files

- **The notes vault is the only place on the NAS Kit can write**, and he
  writes only when you ask. Every other share is read-only, and `kit check`
  fails one he could write to. See [[Notes on the NAS]].
- **Everything Kit owns stays in his data folder.** See [[Settings and Data]].
- **Your documents are read only from the folders you choose** (roots, see
  [[Your Files]]), never changed, and what he reads stays in his memory file
  on the server. He starts with no folders. Removing one takes what he read
  from it out of his memory.
- **A folder can be ticked private.** The tick is kept on every piece read
  from it, and anything the file tools find there reaches a cloud model only
  as the local model's short answer, as below. "Send it to Claude" in a
  message lifts that for the one message. Recall in conversation never
  searches your files; only the file tools do. See
  [[Your Files#Private folders]].
- **A tool can mark what it found private** (a private folder, your
  finances). A cloud model never reads that text: the local model answers
  the question from it in a few words, and only that summary goes out,
  marked as summarised locally. With the local model off, the cloud model is
  only told the answer is in a private source. See
  [[Tools and Packs#Private results]].

## Tokens and secrets

- Every API call needs **Kit's token** (`kit token`). The desk app, the eyes
  and home_app each keep a copy on their own machine; home_app never hands it
  to a browser.
- A device that leaves the house, like a phone, gets a **token of its own**
  (from the app with Kit's token once, or `kit pair phone`), so a lost phone
  is one `kit devices forget phone` away from locked out. A device's token
  talks to Kit and reads his state, but can't **change settings** (or undo a
  change), read the **face numbers** his eyes know, **list** his bodies and
  devices, or pair or unpair devices: those answer 403 to anything but Kit's
  own token. Only a hash of it is kept. See [[Phone App#Pairing]].
- A test sweeps **every route** the brain serves: each `/api` one must turn
  away a call without the token, except `/api/health`, and anything outside
  `/api` must be one of the listed pages, so a new route can't ship open.
- **API keys** live in the data folder's `secrets/` or the environment, never
  in settings or the repo. See [[Settings and Data#Secrets]].
- The brain answers on this PC only (`brain.host = 127.0.0.1`) until you open
  it to the home network or Tailscale.
- Cloud spend has a **monthly cap** (`cloud.monthly_cap_aud`). See
  [[Models and Routing#The budget]].

## This repo is public

Kit's code and these docs are on public GitHub. Real addresses, places,
network details and the names of people and pets stay in your own
`settings.toml` and memory, never in the repo. Examples use made-up values
(Richmond, NSW; `192.168.1.50`). See [[How These Docs Work]].

## Go deeper
- [[Memory]]: seeing, editing and forgetting what he knows.
- [[Stage 2 - Desk App]]: what the desk app shares, in detail.
- [[Vision Stage 1]]: the eyes' privacy, in detail.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/desk/watch.py`, `src/kit/desk/config.py`: what's read on the PC, and the hidden apps and words.
> - `src/kit/brain.py` (`looking_role`, `own_role`): who answers a question about the PC or the room; `src/kit/prompt.py`: the one-line summaries and the look actions; `src/kit/pc_context.py` and `src/kit/scene_context.py` (`detail`): the full picture.
> - `src/kit/memory.py`: private messages and what comes from them.
> - `src/kit/eyes/recognise.py`: face numbers.
> - `src/kit/credentials.py`: keys and the token; `src/kit/routes/state.py`: the token checks on every route.
