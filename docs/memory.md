# How Kit remembers and finds things

Kit should know you the way a good colleague does: remember what you told it,
notice when something has changed, and know where things are kept, without
being told twice. This page explains how that works. Later stages build on it.

## One index for everything Kit knows

Everything Kit can recall lives in one searchable index (`kit/knowledge.py`)
inside `state/memory.db`. Each item has a source, a kind, its text, dates and
a reference back to where it came from.

| Source | What's in it | Added in |
| --- | --- | --- |
| `memory` | Facts about you: about, preference, project, place, person, plan | Stage 1 |
| `days` | A summary of each finished day | Stage 1 |
| `things` | The register of things: one entry per person, vehicle, place, project or equipment, with where it lives | Stage 1 |
| `thing-suggestions` | Names Kit met and suggested adding, waiting for a yes or no | Stage 1 |
| `conversation` | Every exchange, so old conversations can be found | Stage 1 |
| `self` | Kit's own notebook: his thoughts, opinions, wants, moments and daily journal ([life.md](life.md)) | Inner life |
| `self-sheet` | Who Kit thinks he is, in his own words, every version, and the weekly reviews of it. Always in his prompt, so never recalled | Inner life |
| `projects` | Your code projects: path, purpose, state, recent work | Stage 4 |
| `files` | NAS documents and folders (names, paths, text) | Stage 5 |
| `photos` | Photo dates, places, people and captions | Stage 5 |
| `notes` | Your Obsidian vault, by note and heading, kept in step with the files ([your notes](notes.md)) | Now |

A later stage adds a source by putting items into the same index. Recall,
search, the memory page and the accuracy test then work for it with no other
changes.

## Finding things: words and meaning

Every search runs two ways and merges the results:

- **Words**, with SQLite full-text search. This catches exact names, numbers
  and file names ("home_app", "C:\Dev", "2023").
- **Meaning**, with vectors from a small embedding model in Ollama
  (`nomic-embed-text`). This catches the same idea in different words:
  "where's my tax stuff?" finds "tax returns are in Documents/Finance/Tax".

A match only counts if it's close enough in meaning (`memory.min_similarity`).
Sharing a common word like "called" doesn't drag in an unrelated memory, and a
question about something Kit was never told recalls nothing. That's what lets
Kit say "I don't know" instead of guessing.

If the embedding model is down, Kit searches by words alone and the status
says so. Nothing is lost: missing vectors are filled in once it's back.

## Every turn

1. Kit searches for memories relevant to your message: up to 8 facts or day
   summaries (weighed by how much each matters and how lately it came up, see
   below), up to 4 older conversation snippets, and up to 3 entries from his
   own notebook (`memory.own_memories`), so he remembers what he thought, not
   only what you said.
2. Those go into the prompt with their dates, along with pinned facts, which
   are always there. The prompt tells Kit that newer memories win and never
   to invent one. His own notes are marked as his, so they're never taken for
   facts about you.
3. If you mention something Kit can't see, it can search deeper (the `recall`
   action) and then answer with what it found, or say it doesn't know.
4. The exchange is indexed, so it can be found later.

Cloud models get the same memories, whether Kit hands a question over or the
cloud answers first, and can use the same recall and remember actions.

## The register of things

Facts say what's true; the register says where things are. Like a plant tag
register, it has one entry per person, pet, vehicle, place, project or piece of
equipment, with:

- its name and other names ("Hilux", "the ute");
- a few words about it;
- a link into each system where it lives: Home Assistant (area or entity),
  home_app (record), NAS (folder), MetTools (folder), Obsidian (note), code
  (project folder).

Every turn, things named in the message (by name or other name, as whole
words) come first, then the closest entries by words and meaning, up to
`memory.relevant_things` (5). They go into the prompt as "Things you know and
where they live", so Kit looks in the right place first.

Kit uses the `thing` action when you name something. A new name becomes a
suggestion for you to confirm with "yes" (or on the chat or memory page); a
place for a known thing ("no, it's in Tax/2023") replaces that system's link.
Each change is a new version that supersedes the old one, so the history is
kept. The code is `kit/things.py`; entries keep their links in the item's
`meta`, so no schema change was needed.

`kit eval routing` checks that questions bring back the entry linked to the
right system and place: a built-in set on a scratch register, and your own
questions from `config/routing-questions.toml` against the real one.

## What matters, and what's only lately

Each fact has an **importance** (people and things about you count most, a
passing remark least; the end-of-day pass rates each one 1 to 5) and a **last
recalled** time. Recall finds twice as many relevant facts as it needs, then
keeps the ones that matter more and came up lately: each counts from
`memory.weight_floor` (0.3) up to 1, half importance and half how recently it
was recalled or learned (halving every 30 days). Pinned facts count fully. A
floor of 1 turns the weighting off.

Two kinds of fact know about time:

- **now**: how things are lately ("Dan's been sleeping badly", "Sarah's away
  this week"). They go after `memory.now_days` (14) and can never be pinned.
- **plan**: something on a date. The date is worked out when it's learned
  ("the dentist on Thursday" said on Tuesday is 8 October) and shown with it,
  and once it's past the prompt says so.

## Learning without making a mess

A memory that only ever adds things fills up with near-copies and stale facts.
So a new fact is compared with the five closest facts Kit already has, and the
local model decides:

- **same:** it's already known, so nothing is added;
- **update:** it changes a fact ("I sold the Hilux, I drive a Ranger now"), so
  the new fact supersedes the old one, which stays in its history;
- **new:** it's about something else, so it's added.

Facts come from three places: "remember that..." in conversation, who someone
is to you when you say it ("Emma's my cousin", "my partner's name is Sarah",
"the cat's called Milo"), and the end-of-day pass, which writes the day's
summary and learns its lasting facts.

A fact is something lasting about your life: who you are, the people and pets
in it, what you like, what you're working on, where things are kept, what's
coming up. A log of the chat ("Dan asked about pump cavitation") isn't one,
nor is a quiz answer or the weather; a question that shows something lasting
("you're weighing up a used 3090") is kept as that. Every model that saves a
fact is told this, and what each kind is for, so the cat goes with people and
your hobbies with you rather than under "other".

The end-of-day pass runs after midnight. By default (`memory.day_pass =
work`) the work model (Sonnet) reads the day, picks its facts and compares
each with what Kit knows, for a few cents a night; the local model steps in if
the cloud can't. A day with anything you kept local is read at home, always.
`memory.day_pass = local` keeps the whole pass on the local model.

Who someone is to you is always an update: "Emma's my cousin" when Kit had
"Emma, Dan's sister, celebrates her birthday on the 14th of March" becomes
"Emma, Dan's cousin, celebrates her birthday on the 14th of March", keeping the
birthday, with the old fact in its history. Kit looks through every fact naming
Emma for this, not only the closest five. A "now" fact never replaces a lasting
one: "been sleeping badly" is added beside "usually sleeps like a log".

## What you keep local

"Keep it local" keeps that message, and Kit's answer to it, away from every
cloud model: not just for that turn, but in the history, recall, the nightly
reflection and the weekly review too. What Kit keeps from it is marked private
and stays home the same way: facts learned from it, the summary of a day with
one in it, a reminder you asked for that way (and the line he said for it), a
thought he had right after, and a journal or "what's going on with you" written
at home from any of these. The local model still sees all of it.

## You stay in charge

- The memory page (`/memory`) and `kit memory ...` show everything Kit knows,
  grouped by kind, with search, edit, pin, history and forget. Forgetting
  removes a fact and all its earlier versions.
- `kit memory tidy` sorts what Kit already knows by the same rules: each fact
  to the kind that fits, logs of chats and trivia dropped, a log that shows
  something lasting reworded as that. It shows the plan first; `kit memory
  tidy --apply` does it after a backup. A moved fact keeps its old version in
  its history, pinned facts are never dropped, and private facts are only
  ever read by the local model.
- The memory page and `kit things ...` show the register, with links,
  suggestions to confirm or reject, other names, history and forget.
- The memory page's **Kit's notebook** tab (and `kit life notebook`) shows
  Kit's own notes, journal, self-sheet and quirks, with forget and undo.
- `kit eval memory` measures accuracy on a scratch memory: right fact
  recalled, nothing recalled for unknown things, no stale or duplicate facts.
  Run it after changing models or memory settings.
- Memory is backed up daily to `backups/`, and the database records its
  schema version so future upgrades can migrate it safely.
