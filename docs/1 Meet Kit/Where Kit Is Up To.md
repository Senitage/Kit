---
tags: [meet-kit, topic/status]
aliases: [Status, What's built]
summary: What's built and merged into main, what's open, and what's next. Update this note whenever a pull request lands.
---

# Where Kit is up to

*As of 13 October 2026.* The plan behind this is in [[Roadmap]].

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
| Body feed and knowing who can hear him (the Pod's link to the brain) | Done, pull request #36 | [[Pod In Depth#The body feed]] |
| Naps, turning in and waking by himself | Done, pull request #37 | [[Inner Life]] |
| Companion stage 4: his voice and eyes carry it | Done | [[Companion Stage 4]] |
| Faster voice: Chatterbox Turbo's token loop as a CUDA graph, and no 2 s wait connecting from Windows | Done | [[Voice#Faster on a graphics card]], [[Desk App#Connections]] |
| Phone app, phase 0 (the brain's side): pairing from the app, hello, history pages; the desk on several PCs | Done | [[Phone Stage 0 - Pairing]] |
| Review fixes: one cloud connection kept, the embedding model kept loaded, small bugs | Done, pull request #47 | [[Models and Routing]], [[Memory]] |
| Review fixes: the settings file holds only what you changed, every desk test runs in CI, the privacy note says what reaches the cloud, `kit docs check` | Done, pull request #50 | [[Settings Reference#What the file holds]], [[Privacy]], [[Commands#The docs]] |
| Inner life fixes: sulks pass, quiet on a bad night, the keyboard beats the camera, a restart mid-day, look events apart, the plan says what he brought up | Done, pull request #51 | [[Inner Life]], [[Inner Life In Depth]] |
| Fast path: note requests off the main line, forecast while recalling, one embed a turn, Haiku without thinking, connections kept warm | Done, pull request #48 | [[Life of a Message]], [[Notes on the NAS]], [[Models and Routing]], [[Voice]] |
| Cache layout: the conversation served from Claude's cache too, cache use in the spend log, retries for GPT and Gemini | Done, pull request #49 | [[Models and Routing#Caching]], [[Memory In Depth#The spend log]] |
| One voice: his register decided once in the persona (plain neutral English), the prompt says how he sounds once, at most two asides a message, moods phrased for replying and for being alone, guilt-free example lines, a goodbye only when it's the whole message | Done, pull request #55 | [[Who Kit Is]], [[Brain#One voice, two asides at most]], [[Inner Life In Depth#In conversation]] |
| Memory that scales: vectors kept in step not rebuilt, one search a turn off the event loop, recency from telling not recalling, learning after the reply, the replay eval | Done, pull request #54 | [[Memory In Depth#Keeping it fast as memory grows]], [[Evals]] |
| Less keyword, more judgement: the plan reads the message and decides over the word tables, a bad night only when the model agrees, a long quiet or new subject as a hint not a cut, one private flag, history as words, a one-line speaking note | Done, pull request #57 | [[Brain#The reading: judgement over keywords]], [[Inner Life In Depth#A bad night]], [[Privacy#Keep it local]] |
| Desk and eyes reliability, privacy: hidden apps safe from reused process ids, a life feed that outlives bad answers, eyes that report from a thread and keep events, device tokens kept off settings and faces, quiet bodies dropped | Done, pull request #52 | [[Desk App]], [[Eyes]], [[Privacy#Tokens and secrets]] |
| First sound: the first piece at a four-word clause, no watermark, the voice's conditioning worked out once, interrupting him drops the old reply's sentences, "not yet" while the engine loads, no boop over his first word | Done, pull request #53 | [[Voice#How a sentence becomes sound]], [[Desk App#His voice and face on the desk]] |
| Streaming voice: each sentence played in pieces as it's made, his mouth following the sound, a varied opening sound for his mood | Done, pull request #56 | [[Voice#How a sentence becomes sound]], [[Face#The rig, in three layers]], [[API]] |
| Tidy: the server's routes in one file per part of Kit sharing one app state, `kit eval` in its own module, duplicated helpers folded, a test that every route needs the token and one that kept-local words reach no cloud call | Done, pull request #58 | [[API]], [[Code Map]], [[Privacy#Keep it local]] |
| `kit memory scrub`: take out lines that should never have been said, and everything kept of them | Done, pull request #59 | [[Memory In Depth#You stay in charge]] |
| Lite eyes: the eyes on a CPU, a few looks a second, the detector resting between looks | Done, pull request #45 | [[Eyes#Without a graphics card]] |
| Models as your own list (`kit models add` and `remove`, no presets) and prices fetched daily in Australian dollars, the budget and every spend figure in A$ | Done, pull request #60 | [[Models and Routing#Your own list of models]], [[Models and Routing#Prices, fetched for you]] |
| Hearing, companion stage 5: he hears you, answers out loud, stops when talked over, knows voices (also stage 3 part 2) | Done, pull request #42 | [[Hearing]], [[Companion Stage 5]] |
| Stage 4, part A1: the tool loop. Cloud models call tools natively, the local model's action joins the same loop, the core pack (recall, the PC, the room, the forecast, a note), every call logged | Open, pull request #61 | [[Tools and Packs]], [[Stage 4 - Tools]] |
| Stage 4, the rest: pack matching and a yes before changes, files, PC control, the house, the notes vault, your apps and MCP, the morning brief | Not started | [[Stage 4 - Tools]], [[Roadmap]] |

## What's next

1. Companion stage 5 (hearing, #42) tested on the desk.
2. The Pod as his first robot body: the body feed (#36), then voice and
   presence in the room.
3. Stage 4: the tool loop first (#61), then PC control, the Claude Code
   bridge, MCP, Home Assistant, and the home_app and MetTools connections
   ([[Stage 4 - Tools]]).
4. Stages 5 to 8, then the arm.

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
| 13 Oct | Body feed and knowing who can hear him; naps and sleep; hearing (companion stage 5) | #36, #37, #42 |
| 13 Oct | The whole-codebase review: faster first words, Claude's cache, one voice, memory that scales, inner life and desk fixes, streaming voice, judgement over keywords, settings as changes only, routes tidied | #47 to #58 |
| 13 Oct | `kit memory scrub` | #59 |
| 14 Oct | Stage 4 begins: the tool loop and the core pack | #61 |

## Keeping this note true

When a pull request merges, move its row from "Open" to "Done" above, add it
to the history table, and update the notes it changed. The checklist is in
[[How These Docs Work#When you change Kit]]. `kit docs check` reads this note
and points out a row that says open for a pull request the history table
says landed ([[Commands#The docs]]).
