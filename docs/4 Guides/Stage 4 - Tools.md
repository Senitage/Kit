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

## Part A2: which packs load, asking first, and the tool evals

The second part gets ready for more packs. Each message loads only the packs
it needs, chosen before any model is asked (always core; then a pack's
match words, a register thing in that pack's system, or meaning). A tool that
changes something of yours waits for your yes. A tool can mark what it
found private, and a cloud model then only gets the local model's summary.
And `kit eval tools` checks each question reaches the right tool. With only
the core pack installed, nothing you see changes yet: it's the groundwork
the next packs plug into. See [[Tools and Packs#Which packs load]] and
[[Tools and Packs#Asking first]].

### 1. Update and restart Kit

Update as in [[Updating Kit]]. Nothing new to install. The new settings
(`tools.packs`, `tools.max_packs`, `tools.match_similarity`, `tools.confirm`,
`tools.confirm_lapse_minutes`) are in [[Settings Reference#tools]]; the
defaults are fine.

### 2. Test before moving on

- [ ] **One pack for small talk:** say "Morning". `GET /api/status` shows
  `tools.loaded` as `["core"]` and `tools.pending` as null.
- [ ] **Two looks still work:** "What's the weather, and what did I tell you
  about the Pod last week?" Both are answered in one turn, with two tool
  lines in the desk chat.
- [ ] **Notes untouched:** "Take a note: order filament" still writes it
  without asking; "that's worth noting" still offers first.
- [ ] **The expert still asks:** "Think hard about..." still goes to Opus
  after your yes.
- [ ] **The tools, by hand:** `kit tools packs` shows `core  always`;
  `kit tools list` shows the five core tools, none asking first;
  `kit tools run recall --args '{"query": "Pod"}'` prints what he'd find.
- [ ] **The eval, offline:** `kit eval tools` passes every case.
- [ ] **The eval, live:** `kit eval tools --live` passes on the server, with
  each case's spend under A$0.05.
- [ ] **Voice:** his first words still start before any tool runs.
- [ ] **Tests:** `pytest -q tests/test_tool_match.py tests/test_tool_confirm.py
  tests/test_tool_private.py tests/test_evals_tools.py tests/test_routes_tools.py`
  passes on the server.

Asking first can't be tried in a chat yet, because no installed tool
changes anything. It gets its own checklist line with the first pack that
has one (your notes, part E, or your files, part B2).

## Part B1: your files, indexed

Kit reads the folders you choose into his memory: every PDF, Word file,
spreadsheet, slide deck and text file, a page or sheet at a time, with the
years, amounts and references in each piece picked out. They're searchable on
the memory page and with `kit memory search`; asking about them mid-chat
comes with the file tools in part B2. See [[Your Files]].

### 1. Update, install the readers and choose folders

Update as in [[Updating Kit]], then install the file readers in Kit's venv:

```
pip install -e ".[files]"
```

For scanned PDFs, also `pip install -e ".[ocr]"` and the programs it needs
(`sudo apt install tesseract-ocr poppler-utils`). Then add a folder, on the
settings page under "Your files" or here (a made-up path; use your mount):

```
kit files add finance /mnt/nas/Finance
kit files index
```

The first `kit files index` shows each file as it reads it. The new settings
are in [[Settings Reference#files]]; the defaults are fine.

### 2. Test before moving on

- [ ] **`kit check`** has a `files` line saying PDF, Word, Excel and slides
  can be read, and a `files: finance` line saying the folder is readable and
  read-only.
- [ ] **The first run** finishes; `kit files status` shows files and pieces
  for each folder, the last run, and any files it couldn't read.
- [ ] **Finding a document:** `kit memory search "rates notice 2025"` finds
  the notice, with its folder, path and page under the hit. The memory page's
  search shows the same.
- [ ] **Only the files:** `kit files search "insurance renewal"` lists file
  hits only.
- [ ] **Keeping up:** copy a new PDF into the folder; within
  `files.sync_every_minutes` (or after "Look for changes now" on the settings
  page) it's found, with no restart.
- [ ] **Skipped:** a file bigger than the folder's size cap (50 MB), anything
  under `@eaDir` or `#recycle`, and Office's `~$` lock files aren't indexed.
- [ ] **Settings page:** "Your files" lists the folder with its counts. Adding
  a path that doesn't exist says so and saves nothing. Ticking Private sticks
  after a reload. Remove asks first, and the folder's pieces leave memory
  (the folder itself is untouched).
- [ ] **NAS asleep:** with the share unmounted, a sync changes nothing and
  `kit files status` says the folder can't be reached; nothing is forgotten.
- [ ] **Chat untouched:** Kit doesn't bring up your files in conversation yet.
- [ ] **Tests:** `pytest -q tests/test_files.py` passes on the server.

## Part B2: asking about your files

Now he can answer from your documents mid-chat. The `files` pack loads when
a message is about them, and finds, reads and lists them from the index
B1 built. A private folder's text reaches a cloud model only as the local
model's short answer. See [[Your Files#Asking about them]].

### 1. Update and restart Kit

Update as in [[Updating Kit]]. Nothing new to install or set. For the
private test, tick one folder Private on the settings page, and keep the
local model running.

### 2. Test before moving on

- [ ] **A figure from a document:** "What did I pay for the rates last
  year?" gives the right amount and names the notice. The desk chat shows a
  `find_documents` line (and maybe `read_document`).
- [ ] **A folder:** "What's in the Finance folder?" lists its folders and
  newest files.
- [ ] **A register link:** with a project in the register linked to its NAS
  folder (`kit things link ID nas Projects/Riverbend`), "bring up everything
  on Riverbend" looks in that folder first.
- [ ] **Have you got them:** "Have you read my files?" says which folders and
  how many files.
- [ ] **Private:** ask about a document in the private folder. The answer
  has the figure. Stop the local model (`sudo systemctl stop ollama`) and ask
  again: he says it's in a private folder he can only read locally, and
  doesn't make up a figure. Start it again after.
- [ ] **Lifting it:** "Send it to Claude: what does the lease say about
  pets?" answers from the text itself.
- [ ] **No files talk unasked:** "Morning" loads only `core`
  (`/api/status`, `tools.loaded`).
- [ ] **The eval:** `kit eval tools --pack files` passes offline, and with
  `--live` on the server.
- [ ] **Tests:** `pytest -q tests/test_tools_files.py` passes on the server.

## Parts to come

In order, each with its own section here when it lands: opening files and apps on the PC (C); the house
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
- **A pack didn't load when it should have:** `tools.loaded` on
  `/api/status` shows what the last message loaded. Add the word to the
  pack's match words, or a question like yours to `tool-questions.toml` and
  run `kit eval tools` to see why. Lowering `tools.match_similarity` loads
  more by meaning.
- **He asked to do something and then forgot:** an offer lapses after
  `tools.confirm_lapse_minutes`, or when your next message isn't a yes or a
  no. Ask again.
- **"There is no tool called ...":** the model asked for a tool it wasn't
  offered this turn, or one from a pack that didn't load. The result tells it so and it answers without; if it
  keeps happening, raise it as a bug with the line from `tools.recent`.
