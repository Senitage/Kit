---
tags: [guide, stage, topic/tools]
aliases: [stage-4, Stage 4]
summary: Stage 4, tools and PC control - the tool loop first, then the packs (files, PC, house, notes, apps), with the test checklist for each part as it lands.
related: ["[[Tools and Packs]]", "[[Roadmap]]", "[[The House]]"]
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

## Part C1: doing things on your PC

Kit can open files, folders, apps and sites on the PC you're on, bring a
window up, pause the music, and say what you worked on and which code
projects you have. The PC decides what's allowed. See
[[Desk App#Doing things on the PC]] and [[Desk App#What you worked on]].

### 1. Update Kit and the desk app, and set it up

Update as in [[Updating Kit]], and let the desk app install its update. On
the desk app's This PC page, under **What Kit may open**, add the folders
you want him to open (your code folder, `\\NAS\finance`) and check the app
list. For your files to open, set each folder's `pc_path` on the settings
page (`files.roots.finance.pc_path = "\\NAS\finance"`). For code projects,
set `projects.roots` to the server folder holding them and `projects.pc_roots`
to where the PC sees it.

### 2. Test before moving on

- [ ] **A folder:** "Open my Documents folder" opens it in Explorer, and
  Kit says so.
- [ ] **A found document:** "Find the rates notice and open it" opens the
  PDF from the NAS.
- [ ] **An app and a site:** "Open Excel", then "open github.com".
- [ ] **Not allowed:** "Open C:\\Windows" doesn't, and Kit says it isn't in
  a folder the PC lets him open. The This PC page's **What he's done** shows
  both.
- [ ] **A window and the music:** with a song playing, "pause the music",
  then "bring Excel to the front".
- [ ] **Desk app closed:** quit it and ask him to open something: he says he
  can't reach the PC.
- [ ] **Switched off:** untick **Let Kit open...**, ask again: he says this
  PC has it turned off.
- [ ] **On the phone:** from the phone app, "open the Riverbend folder" opens
  it on the PC and he says it's on the PC.
- [ ] **What you worked on:** after a day of use, "what was I working on
  yesterday?" names the apps, files and projects.
- [ ] **Projects:** "what code projects have I got?" lists them with their
  last commit; "open the Pod project" opens it in VS Code.
- [ ] **The eval:** `kit eval tools --pack pc` passes offline.
- [ ] **Tests:** `pytest -q tests/test_desk_commands.py tests/test_desk_run.py tests/test_activity.py` passes.

## Part D1: the house, through Home Assistant

Kit can see and switch what you expose to him in Home Assistant: lights,
switches, the aircon, scenes, blinds, the garage and locks, and who's home.
Locks and alarms always ask first, the garage asks every time, and the
aircon once a day. He also notices someone getting home, a door opening
after dark and a light left on. See [[The House]].

### 1. Update Kit and set up his Home Assistant user

1. Update as in [[Updating Kit]] (`pip install -e .` brings in
   `websockets`).
2. In Home Assistant: Settings, People, Users, add a user called Kit with
   **Administrator off**. Log in as Kit, open the profile, Security, and
   create a **long-lived access token**.
3. Save the token on the server as `secrets/home_assistant_token` in Kit's
   data folder (owner-only, like the other secrets).
4. In Home Assistant: Settings, Voice assistants, **Expose**. Expose only
   what Kit may see and switch: a few lights, the aircon, a scene, the
   blinds, the garage, the front door lock, and the people.
5. `kit config set house.url ws://192.168.1.60:8123/api/websocket` (your
   Home Assistant's address), `kit config set house.enabled true`, then
   restart Kit.

### 2. Test before moving on

- [ ] **The check:** `kit check` shows a `house` line: "reachable as Kit
  (not an admin), N things exposed to Assist".
- [ ] **What he sees:** `kit house list` lists only the exposed things, each
  with its room and state. Something you didn't expose isn't there.
- [ ] **A lamp:** "turn the study lamp off" switches it straight away, and he
  says so. "Lounge lights to 30 percent" dims them.
- [ ] **A state:** "is the aircon on?" gives its mode and temperature.
- [ ] **Climate once a day:** "set the aircon to 23" asks first; say yes and
  it changes. Ask again with another temperature: no question this time.
- [ ] **Blinds and garage:** "close the blinds" just happens. "Open the
  garage" asks every time.
- [ ] **A lock:** "lock the front door" asks; yes locks it.
- [ ] **No from the phone:** on the phone app, "unlock the front door" is
  refused, even if you say yes, with "it has to be done at home".
- [ ] **Not exposed:** ask for something you didn't expose: he says he
  can't see it.
- [ ] **Which one:** "turn the lights off" with several lights on: he asks
  which.
- [ ] **Who's home:** "who's home?" names the people and home or away.
- [ ] **A register link:** `kit things link ID home_assistant
  switch.shed_heater` on the shed, then "is the shed heater on?" goes
  straight to it.
- [ ] **Noticing:** after dark, open a watched door or the garage: he gets
  curious (`/api/life/events` shows a `house` event) and may mention it.
  Leave a light on for 4 hours: one mention.
- [ ] **Down:** stop Home Assistant (or set a wrong `house.url`): "turn the
  study lamp on" gets "the house is out of reach", and everything else about
  him is fine. Start it again: within a minute or so the house is back
  without restarting Kit.
- [ ] **No house talk unasked:** "Morning" loads only `core`.
- [ ] **The eval:** `kit eval tools --pack house` passes offline.
- [ ] **Tests:** `pytest -q tests/test_house.py` passes.

## Part E1: your notes vault, properly

Kit finds notes and tasks, lists what's due, adds under a heading, ticks a
task off, starts a note from a template, opens one in Obsidian on the PC
and undoes his last change. Edits, ticks and undo show the change first and
wait for your yes, and he never writes over an edit you made meanwhile. See
[[Notes on the NAS#Changing a note]].

### 1. Update and restart Kit

1. Update as in [[Updating Kit]] and restart Kit. The first sync after the
   update reads every note once more, to pick up tasks, tags and links.
2. Optional: if your daily notes or templates aren't set in Obsidian's own
   settings, set `notes.daily_folder` and `notes.templates_folder`.

### 2. Test before moving on

- [ ] **What he sees:** `kit notes shape` lists the vault's folders, daily
  notes, templates, tags and most linked notes, in 8 lines at most.
- [ ] **Tasks:** `kit notes tasks` lists your open tasks; tick one in
  Obsidian, wait for the sync (five minutes) and it's gone.
- [ ] **To-do list:** "what's on my to-do list this week?" lists the tasks
  due this week, soonest first.
- [ ] **Finding:** "find my notes about the shed" names the notes.
- [ ] **Under a heading:** "add check the spigot under This Week in my
  Riverbend log" puts it at the end of that section, straight away.
- [ ] **Ticking:** "tick off order filament" shows the change and asks; yes
  ticks it in the note.
- [ ] **Editing:** "change sandpaper to sanding discs in my shopping list"
  shows the change and asks; no leaves the note alone.
- [ ] **Your edit wins:** ask for a tick, then before saying yes, edit that
  note in Obsidian and save. Say yes: he doesn't write, reads the note again
  and asks once more.
- [ ] **Undo:** after a tick, "undo that" asks, then puts the note back.
  `kit notes undo` with nothing left says there's nothing to undo.
- [ ] **A new note:** "start a note called Shed build from my Project
  template" makes it in the vault with the template filled in.
- [ ] **Opening:** with the desk app running, "open my holiday planner in
  Obsidian" opens it on the PC.
- [ ] **Never unasked:** "I'm out of glue" may offer to note it, never
  writes it.
- [ ] **Sunday:** on a Sunday, `/api/life/events` shows a `notes_tidy`
  event if anything looks untidy, and nothing in the vault changed.
- [ ] **The eval:** `kit eval tools --pack notes` passes.
- [ ] **Tests:** `pytest -q tests/test_tools_notes.py tests/test_notes_edit.py`
  passes.

## Part F1: your apps as packs

Any app with an MCP server becomes a pack of Kit's tools: list it under
`apps.servers` and its tools load when a message is about it. A tool that
changes something asks first, a down app is said to be out of reach, and an
app's saved work goes into his memory once a day. See
[[Other Apps#Apps as packs]].

### 1. Update Kit and add an app

1. Update as in [[Updating Kit]].
2. Put the app's token for Kit in the secrets folder, for example
   `secrets/mettools_token`.
3. Add the app, then restart Kit:

   ```
   kit config set apps.servers.mettools.url http://192.168.1.50:8001/mcp
   kit config set apps.servers.mettools.token_secret mettools_token
   kit config set apps.servers.mettools.words '["pump", "slurry", "calc", "MetTools"]'
   ```

   For a server that runs as a program on the box, set `command` instead of
   `url`, like `'["python", "-m", "kit_mcp.server"]'`.

### 2. Test before moving on

- [ ] **The check:** `kit check` has an `app: mettools` line: "connected to
  MetTools, N tools".
- [ ] **Its tools:** "what can you do in MetTools?" lists its tools
  (`mettools_status`).
- [ ] **A look:** a read-only tool (saved work, a list) just runs.
- [ ] **A change asks:** a tool the server marks destructive, or doesn't
  mark at all, asks first; no leaves it undone.
- [ ] **Your own confirm:** add a harmless tool's name to
  `apps.servers.mettools.confirm`: now it asks too.
- [ ] **Down:** stop the app's server: `kit check` fails its line, and "run
  a pump calc in MetTools" gets "MetTools is out of reach right now", with
  everything else about him fine. Start it again: within five minutes it's
  back without restarting Kit.
- [ ] **Saved work:** with a server that has a `contents` tool, the next day
  `kit memory search` finds its rows, and "find my last pump calc" uses
  `mettools_find`.
- [ ] **Private:** set `apps.servers.home_app.private` true: its answers
  reach Claude only as a local summary.
- [ ] **The phone:** from the phone, "what's in my notes about Riverbend?"
  tells you; "open it" opens it on the PC and he says so.
- [ ] **No app talk unasked:** "Morning" loads only `core`.
- [ ] **Tests:** `pytest -q tests/test_tools_mcp.py` passes.

## Part F2: MetTools in full

MetTools' own MCP server joins Kit as the `mettools` pack: saved work,
calculators with no browser, and the page you have open. Kit starts it
himself and hands it MetTools' address and its token. See
[[Other Apps#MetTools]].

### 1. Set it up on the box

1. Update Kit as in [[Updating Kit]].
2. In the MetTools container, make Kit a token:
   `python manage.py kit_token create`. It prints the key once.
3. On Kit's box, save it as `secrets/mettools_token` in Kit's data folder.
4. Check out MetTools on the box and give its server its own Python:

   ```
   git clone https://github.com/Senitage/METTOOLS.git ~/METTOOLS
   cd ~/METTOOLS && python3 -m venv .venv
   .venv/bin/pip install -r kit_mcp/requirements.txt
   node --version     # 18 or newer, for the calculators; sudo apt install nodejs if not
   ```

5. Add it to Kit's `settings.toml` (your own paths and MetTools' address,
   with its `/tools` prefix if it has one), then restart Kit:

   ```toml
   [apps.servers.mettools]
   command = ["/home/kit/METTOOLS/.venv/bin/python", "/home/kit/METTOOLS/kit_mcp/server.py"]
   env = { METTOOLS_URL = "http://192.168.1.50:8000/tools" }
   token_secret = "mettools_token"
   card = "Dan's engineering calculators and saved work"
   words = ["pump", "slurry", "calc", "calculation", "estimate", "mass balance", "MetTools"]
   ```

### 2. Test before moving on

- [ ] **The check:** `kit check` says "app: mettools ... connected", with
  about 25 tools (more while MetTools is open in your browser).
- [ ] **Find:** "find my last slurry pump calc" names it, with its project.
- [ ] **Read one:** "what was the TDH on it?" reads the saved result, not a
  sum of his own.
- [ ] **Open:** "open it" opens the calc in its tool on the PC.
- [ ] **Run, no browser:** with MetTools closed, "what does that pump need
  at 40% solids?" runs the calculator and gives MetTools' numbers.
- [ ] **Save asks:** "save that as rev B" asks first; no leaves nothing
  saved, yes adds a new draft (the old save is untouched).
- [ ] **The page you have open:** open a pump calc in the browser, then
  "set the flow to 300 and run it": the fields change on screen, and he reads
  the results back.
- [ ] **A note:** "put a note on my screen saying check the NPSH" shows it in
  the corner of the MetTools window.
- [ ] **Estimates and balances:** "what's the total on the latest estimate?"
  and "does the Riverbend mass balance close?" answer from saved work.
- [ ] **Overnight:** the next day `kit memory search "tails pump"` finds the
  calc as an `app:mettools` row.
- [ ] **MetTools down:** stop MetTools: "run a pump calc" gets "MetTools is
  out of reach right now"; start it again and it's back on its own.
- [ ] **Tests:** `pytest -q tests/test_tools_mcp.py` passes.

## Parts to come

In order, each with its own section here when it lands: home_app (F3); the
morning brief (G). The plan is in [[Roadmap]].

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
- **The house is out of reach:** `kit check` says why. A wrong token is
  "auth_invalid"; a changed address is `house.url`. Kit retries on its own,
  backing off to once a minute.
- **He can't find a light you can see in Home Assistant:** it isn't exposed
  to Assist, or its name is very different from what you said. `kit house
  list` shows what he sees and the names he goes by.
- **"There is no tool called ...":** the model asked for a tool it wasn't
  offered this turn, or one from a pack that didn't load. The result tells it so and it answers without; if it
  keeps happening, raise it as a bug with the line from `tools.recent`.
