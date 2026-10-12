---
tags: [meet-kit, topic/status]
aliases: [Status, What's built]
summary: What's built and merged into main, what's open, and what's next. Update this note whenever a pull request lands.
---

# Where Kit is up to

*As of 11 October 2026.* The plan behind this is in [[Roadmap]].

## At a glance

| Part | State | Notes |
|---|---|---|
| Server setup and `kit check` (stage 0) | Done | [[Stage 0 - Server Setup]] |
| Text brain and memory (stage 1) | Done | [[Brain]], [[Memory]] |
| Desk app, face and chat (stage 2) | Done, updates itself | [[Desk App]] |
| Inner life: feelings, thoughts, notebook, nightly reflection | Done | [[Inner Life]] |
| Notes in the NAS vault, only when asked | Done | [[Notes on the NAS]] |
| Companion stages 1 to 3 | Done | [[Companion]] |
| Cloud-only routing: Haiku chats, Sonnet works, ask before Opus | Done | [[Models and Routing]] |
| Character sheets: Retro, Kit 3D, Kit 2D | Done | [[Face]] |
| Voice, part 1 of stage 3: Kit talks | Done | [[Voice]] |
| Eyes, vision stages 1 and 2: he sees you, and knows who's who | Done | [[Eyes]] |
| The Pod: program, printed parts, build guide | Done, in `pod/` | [[The Pod]] |
| Body feed and knowing who can hear him (the Pod's link to the brain) | Open, pull request #36 | [[Pod In Depth#The body feed]] |
| Naps, turning in and waking by himself | Open, pull request #37 | [[Inner Life]] |
| Companion stage 4: his voice and eyes carry it | Open, pull request #40 | [[Companion Stage 4]] |
| Faster voice: Chatterbox Turbo's token loop as a CUDA graph, and no 2 s wait connecting from Windows | Done, pull request #43 | [[Voice#Faster on a graphics card]], [[Desk App#Connections]] |
| Phone app, phase 0 (the brain's side): pairing from the app, hello, history pages; the desk on several PCs | Done, pull request #44 | [[Phone Stage 0 - Pairing]] |
| Phone app, phases 1 and 2: Kit for Android you can install, with chat, his face, waiting messages and updates; then his pipe-ups as notifications you answer in place, home or out and the battery, his Kit, Memory and Settings pages, a widget and a tile | Open, pull request #46 | [[Phone Stage 1 - Pocket Kit]], [[Phone Stage 2 - He's With You]] |
| Hearing: microphone, wake word, speech to text (stage 3 part 2) | Not started | [[Roadmap]] |
| Tools, PC control, the Claude Code bridge (stage 4) | Not started | [[Roadmap]] |

## What's next

1. Companion stage 4 (#40), then stage 5: hearing, with tone.
2. The Pod as his first robot body: the body feed (#36), then voice and
   presence in the room.
3. Hearing: the microphone, wake word and speech to text.
4. Stage 4: a tool loop, PC control, the Claude Code bridge, MCP, Home
   Assistant, and the home_app and MetTools connections.
5. Stages 5 to 8, then the arm.

## How we got here

Every change lands as a pull request on GitHub, tested on Windows and Linux.

| When | What landed | Pull requests |
|---|---|---|
| 6 Oct | Project skeleton, settings and the setup checker | #1 |
| 7 Oct | The text brain: recall-based memory, swappable cloud models, settings pages | #2 |
| 7 Oct | The face: expression rig and the Glow painter | #3 |
| 7 Oct | The desk app for Windows: tray, face, chat, PC context, then a modern chat, Kit's window and self-updates | #4, #5 |
| 7 Oct | Inner life: feelings, thoughts, a notebook and nightly reflection | #6 |
| 7 Oct | Notes in the NAS vault, read in full, written only when asked | #7, #8, #10 |
| 8 Oct | Companion stage 1 (he knows you were gone) and stage 2 (he follows your life) | #12, #13, #14 |
| 9 Oct | Haiku profile and cloud-only routing | #15 |
| 9 Oct | Companion stage 3: a life of his own, and feeling it | #17 |
| 9 Oct | Spend per day and model, and a home_app chat channel | #19 |
| 9 Oct | Character sheets for his face (Retro first), 2D or 3D per app | #20 |
| 9 Oct | Thoughts and pipe-ups can go to the cloud, so the local model leaves the GPU | #21 |
| 9 Oct | Desk app: words under his face, a boop, face shows, a Mood page, bigger moves | #23 |
| 9 Oct | Voice with swappable engines | #24 |
| 9 Oct | Kit 3D on the desk, updated live from the brain | #25 |
| 9 Oct | Example places in the repo instead of real ones | #26 |
| 9 Oct | A custom speech style really changes how he talks | #27 |
| 9 Oct | His face rests on his mood, and he winds down by bedtime | #28 |
| 10 Oct | He starts talking sooner, and the log times each reply | #30, #31 |
| 10 Oct | No slang in his lines; pipe-ups show once in the desk chat | #32 |
| 10 Oct | He stops missing Dan once he's back; good feelings last as long as bad ones | #33 |
| 10 Oct | Kit 2D: the 3D face drawn flat, as a new character | #34 |
| 10 Oct | Eyes stage 1: Kit sees you | #22 |
| 10 Oct | Eyes stage 2: who's who | #35 |
| 11 Oct | These docs as an Obsidian vault; the Pod's program, printed parts and build guide in the repo | #38 |

## Keeping this note true

When a pull request merges, move its row from "Open" to "Done" above, add it
to the history table, and update the notes it changed. The checklist is in
[[How These Docs Work#When you change Kit]].
