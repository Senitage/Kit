---
tags: [how-it-works, topic/privacy]
aliases: [Keep it local, What Kit sees, The switches, Security]
summary: What Kit sees, what leaves the house and what never does - keep it local, the desk app's switches, the eyes' no-pictures rule, read-only shares, tokens and secrets.
related: ["[[Memory]]", "[[Stage 2 - Desk App]]", "[[Vision Stage 1]]"]
---

# Privacy

> [!ABSTRACT] In short
> Kit lives at home: his brain, memory and voice run on your own server.
> Only the words a **cloud model** needs to answer leave the house, and
> **"keep it local"** stops even that for anything you choose. On the PC he
> sees **window titles, never screenshots**; through the camera he sees
> **words and numbers, never pictures**; through the mic he gets **words, never
sound**. Every way in has a **switch**, and
> you can see and forget anything he remembers.

## What stays home, and what goes out

| | Stays on your server | Goes to a cloud model |
|---|---|---|
| Memory, the notebook, the register | always | only the few memories recalled for that message |
| Your messages | always | when a cloud model answers them, unless kept local |
| What's on the PC, the scene from the eyes | always | the one-line summary, with that message |
| His voice | always (the engine runs on the server's GPU) | never |
| The camera | never leaves the PC as a picture | never |
| The microphone | never leaves the PC as sound; only words meant for Kit are kept | his words, when a cloud model answers them |
| Notes in your vault | always | the parts recalled for that message |

Which model answers is in [[Models and Routing]]. Turning `routing.mode` to
`local-heavy` keeps far more at home; the cloud is still there for what the
local model can't do.

## Keep it local

Say **"keep it local"** with a message and it's answered by the local model,
and everything that comes from it is marked private: what he learns, the day's
summary, a reminder, his thoughts about it, his journal. None of it ever goes
to a cloud model, in recall, reflection or review. See
[[Memory In Depth#What you keep local]].

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

## Tokens and secrets

- Every API call needs **Kit's token** (`kit token`). The desk app, the eyes
  and home_app each keep a copy on their own machine; home_app never hands it
  to a browser.
- **API keys** live in the data folder's `secrets/` or the environment, never
  in settings or the repo. See [[Settings and Data#Secrets]].
- The brain answers on this PC only (`brain.host = 127.0.0.1`) until you open
  it to the home network or Tailscale.
- Cloud spend has a **monthly cap** (`cloud.monthly_cap_usd`). See
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
> - `src/kit/memory.py`: private messages and what comes from them.
> - `src/kit/eyes/recognise.py`: face numbers.
> - `src/kit/credentials.py`: keys and the token.
