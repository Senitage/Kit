---
tags: [reference, topic/commands, topic/cli]
aliases: [CLI, kit command, Terminal commands]
summary: Every kit command in one place, grouped by what it's for, with a pointer to the note that explains each part.
---

# Commands

Up: [[Home]] · Reference

Everything runs as `kit ...` in the terminal where Kit is installed (on the
server: `cd ~/Kit && source .venv/bin/activate`). `kit COMMAND --help` shows
the options for any of them.

## Setting up

| Command | What it does |
|---|---|
| `kit paths` | Show where Kit keeps his files. See [[Settings and Data]] |
| `kit init` | Create the data folder and a starter settings file |
| `kit check` | Check this machine is ready to run Kit (`--skip NAME` to skip one) |
| `kit serve` | Run the brain with its pages (`--host`, `--port` override the settings) |
| `kit token` | Show the API token for the desk app, the eyes and home_app |
| `kit pair NAME` | Pair a device (a phone) with a token of its own; shows a QR code (`--kind`, `--address`). See [[Phone App#Pairing]] |
| `kit devices` | List paired devices (`kit devices list` does the same) |
| `kit devices forget NAME` | Unpair a device; its token stops working at once |

## Talking to him

| Command | What it does |
|---|---|
| `kit chat` | Talk to Kit in this terminal (the `terminal` channel) |
| `kit new-chat` | Start a fresh conversation; the old one stays in memory |

## Settings

| Command | What it does |
|---|---|
| `kit config show` | Print the settings in force |
| `kit config set KEY VALUE` | Change one setting, e.g. `kit config set persona.name Kit` |
| `kit config undo` | Go back to the settings before the last change |
| `kit config history` | List earlier versions |
| `kit config restore VERSION` | Go back to an earlier version |
| `kit config reset` | Back to the defaults (memory is untouched; undo restores) |
| `kit config check` | Check the settings file is valid |
| `kit config schema` | Print the settings schema as JSON |

Every setting is in [[Settings Reference]].

## Models

| Command | What it does |
|---|---|
| `kit models` | The models Kit uses for each role |
| `kit models ROLE NAME` | Switch a role (`chat`, `work` or `expert`) to another model profile, e.g. `kit models work opus` |

See [[Models and Routing]].

## Inner life

| Command | What it does |
|---|---|
| `kit life` (`kit life show`) | His mood, feeling and why, drives, what he's thinking, what's coming up |
| `kit life poke` | Make him pipe up now |
| `kit life think` | Have a private thought now |
| `kit life reflect` | Do tonight's look back now |
| `kit life notebook` | His notebook: thoughts, opinions, wants, journal, self-sheet |

See [[Inner Life]].

## Memory

| Command | What it does |
|---|---|
| `kit memory facts` | List what Kit knows (`*` = pinned) |
| `kit memory remember TEXT` | Teach him a fact (`--kind` to say which kind) |
| `kit memory search QUERY` | Search memory the way Kit does |
| `kit memory pin ID` / `unpin ID` | Keep a fact always in mind, or stop |
| `kit memory forget ID` | Delete a fact (and its history) or a recalled conversation |
| `kit memory history ID` | A fact's earlier versions |
| `kit memory days` | The day summaries |
| `kit memory summarise` | Summarise finished days now |
| `kit memory tidy` | Plan sorting what he knows into the right kinds; `--apply` does it, after a backup |
| `kit memory reindex` | Build any missing meaning vectors now |
| `kit memory backup` | Back up memory now |
| `kit memory spend` | This month's cloud spend, and for each recent call the input tokens read from the prompt cache (`cached 1830/2400`) |

See [[Memory]].

## The register of things

| Command | What it does |
|---|---|
| `kit things list` | The register |
| `kit things add NAME` | Add a thing, e.g. `kit things add Hilux --kind vehicle --link nas=Cars` |
| `kit things link ID SYSTEM TARGET` | Set where a thing lives in one system |
| `kit things suggestions` | Names Kit suggested adding |
| `kit things confirm ID` / `reject ID` | Add a suggestion, or drop it |
| `kit things forget ID` | Delete a thing |
| `kit things history ID` | A thing's earlier versions |

See [[Register of Things]].

## Notes and weather

| Command | What it does |
|---|---|
| `kit notes` | Read the notes vault now and list what Kit sees. See [[Notes on the NAS]] |
| `kit weather [PLACE]` | The forecast Kit sees, for `persona.location` or PLACE. See [[Time and Weather]] |

## Voice

| Command | What it does |
|---|---|
| `kit speech` (`kit speech show`) | The voice engines, which one's in use and the fallback, on or off |
| `kit speech use ENGINE` | Switch engine, e.g. `kit speech use chatterbox-turbo` |
| `kit speech on` / `off` | Speak replies in the desk app, or stop (frees the engine's memory) |
| `kit speech say TEXT` | Say a line and show how long it took (`--engine`, `--mood`) |
| `kit speech bench` | Compare engines on the same lines (`--engines`), with whether each fits the graphics card |

See [[Voice]].

## Eyes

These run on the PC with the camera.

| Command | What it does |
|---|---|
| `kit eyes` | Run the eyes (`--show` for a window, `--camera`, `--name`) |
| `kit eyes cameras` | The cameras on this machine |
| `kit eyes connect URL TOKEN` | Save where the brain is |
| `kit eyes show` | What Kit can see right now, as he's told it |
| `kit eyes enrol WHO` | Introduce someone (`me` for you), from the camera or `--photos` |
| `kit eyes faces` | Who his eyes know |
| `kit eyes forget WHO` | Forget someone's face completely |
| `kit eyes pause` / `resume` | Switch the eyes off (the camera is released) or on |

See [[Eyes]].

## Hearing

These run on the PC with the microphone.

| Command | What it does |
|---|---|
| `kit hearing` | Run the ears (`--name` for the mic, `--brain`, `--token`; `--words` shows the words they hear, in that window only) |
| `kit hearing mics` | The microphones on this machine |
| `kit hearing connect URL TOKEN` | Save where the brain is |
| `kit hearing show` | Whether the ears are listening, and what Kit last made of something (never the words) |
| `kit hearing enrol WHO` | Introduce someone's voice (`me` for you): they read a few lines aloud |
| `kit hearing voices` | Whose voices his ears know |
| `kit hearing forget WHO` | Forget someone's voice completely |
| `kit hearing pause` / `resume` | Switch the ears off (the mic is let go) or on |

See [[Hearing]].

## Evals

| Command | What it does |
|---|---|
| `kit eval replies` | Whether local replies come back in shape, and how fast the first words arrive |
| `kit eval memory` | Memory recall, and a suggested `memory.min_similarity` |
| `kit eval memory --replay SNAPSHOT [--questions FILE]` | Your own questions against a copy of a memory snapshot (a backup): does the right fact still come first? |
| `kit eval routing` | Whether Kit knows where things live, from the register |
| `kit eval compare --models A B` | Compare cloud models on the same questions |
| `kit eval voice --models A B` | Which local model sounds most alive |
| `kit eval companion` | How good a companion he is |
| `kit eval mood` | How well he reads your mood |

See [[Evals]].

## The docs

| Command | What it does |
|---|---|
| `kit docs check` | Report rows of [[Where Kit Is Up To]] that look stale, with no network: a part marked "Open, pull request #N" whose #N is in the "How we got here" table is **stale** (exit code 1); one with a number lower than the newest landed pull request is **worth a look**; one marked "(number to come)" **needs its number**. `--vault PATH` for a docs folder other than this checkout's |

## The desk app

`kit-desk` starts the desk app from a clone (the installed app has its own
shortcut). See [[Desk App]].
