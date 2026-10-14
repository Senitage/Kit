---
tags: [guide, stage, topic/tools]
aliases: [stage-4, Stage 4]
summary: Stage 4, tools and PC control - the tool loop first, then the packs (files, PC, house, notes, apps), with the test checklist for each part as it lands.
related: ["[[Tools and Packs]]", "[[Roadmap]]"]
---

# Stage 4: tools and PC control

Up: [[Home]] · Guides · [[Tools and Packs]]

Stage 4 is where Kit starts doing things, not only knowing them: searching
your files, opening what you're working on, turning the lights down, taking
your notes properly, driving your own apps. It's built in parts, each its
own pull request, so this guide grows a section per part. Finish
[[Companion Stage 5]] first; this stage assumes a working brain with the
cloud models set up ([[Models and Routing]]).

How it works is in [[Tools and Packs]].

## Part A1: the tool loop

The first part replaces the one look he could do mid-answer with a proper
loop: the model asks for a tool, the brain runs it and hands the result back,
and the model answers from it, up to `tools.hops` times a turn. The looks he
already had (his memory, the PC, the room, the forecast, a note) are the
first pack, `core`. Nothing new to set up: the memory file gains a
`tool_calls` table by itself on the first start.

### 1. Update and restart Kit

Update as in [[Updating Kit]]. No new package, key or setting is needed.
`tools.hops` (6) is there if you want it lower or higher.

### 2. Test before moving on

- [ ] **A recall through a cloud model:** with `routing.mode` at
  `cloud-only`, ask about something he was told a while ago ("where did I
  say my tax returns were?"). A small line appears in the chat while he
  searches, then the answer. No empty bubble before it.
- [ ] **Words first:** ask something where he's likely to say "Let me
  think..." before looking. The words are spoken, then the look, then the
  answer, as one message.
- [ ] **Two looks in one turn:** "is tomorrow going to be nicer than today
  was?" He checks the forecast and looks back at today, then answers. On the
  memory page the turn shows one answer, not two.
- [ ] **Nothing to look at:** "Morning." No tool is called and nothing is
  logged under `tools.recent` on `/api/status`.
- [ ] **Keep it local:** "keep it local: what have I got open?" The local
  model's own `look_at_pc` action still runs through the loop; no cloud call
  is made (`/api/spend` shows nothing new).
- [ ] **The log:** `GET /api/status` lists `core` under `tools.packs` and the
  calls just made under `tools.recent`.
- [ ] **Tests:** `pytest -q tests/test_tools.py` passes on the server.

## Parts to come

In order, each with its own section here when it lands: pack matching, a
yes before anything that changes something, and `kit eval tools` (A2); your
files indexed and found (B); opening files and apps on the PC (C); the house
through Home Assistant (D); your notes vault, properly (E); your own apps and
MCP (F); the morning brief (G). The plan is in [[Roadmap]].

## If something's off

- **He makes something up instead of looking:** check the model's request
  carried the tools: `kit config get tools` shows `hops`, and the prompt
  has a "Tools:" paragraph when a cloud model answers. The local model never
  gets native tools; it uses its `action`.
- **He looks twice at the same thing:** he shouldn't; a repeat call with the
  same arguments is answered from the first. A repeat with different
  arguments is allowed up to `tools.hops`.
- **"There is no tool called ...":** the model asked for a tool it wasn't
  offered this turn. The result tells it so and it answers without; if it
  keeps happening, raise it as a bug with the line from `tools.recent`.
