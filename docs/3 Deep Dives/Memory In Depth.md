---
tags: [deep-dive, topic/memory]
aliases: [memory.md, Memory design]
summary: The full design of Kit's memory - one index, finding by words and meaning, the register of things, what matters, learning tidily, keeping things local.
---

# How Kit remembers and finds things

Up: [[Home]] · Deep dives · [[Memory]]

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
| `self` | Kit's own notebook: his thoughts, opinions, wants, moments and daily journal ([[Inner Life In Depth]]) | Inner life |
| `self-sheet` | Who Kit thinks he is, in his own words, every version, and the weekly reviews of it. Always in his prompt, so never recalled | Inner life |
| `projects` | Your code projects: path, purpose, state, recent work | Stage 4 |
| `files` | Your documents in the folders you chose: a piece of about 400 words per item, its `root:path` as the ref, page, folder, time, size, private flag and the years, amounts, dates and references in it ([[Your Files]]). Searched on the memory page and by `kit memory search`; the file tools bring it into conversation | Stage 4 (B1) |
| `photos` | Photo dates, places, people and captions | Stage 5 |
| `notes` | Your Obsidian vault, by note and heading, kept in step with the files ([[Notes Setup|your notes]]) | Now |
| `seen` | What Kit's eyes saw that's worth remembering: someone arriving after the desk was empty a while, the cat wandering in ([[Vision Stage 1|his eyes]]) | Vision 1 |

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

### Keeping it fast as memory grows

The meaning search is one dot product of the message's vector against a
matrix with one row per current item. That matrix lives in memory and is
**kept in step** with the index rather than rebuilt: a saved vector is
appended as a row, and a superseded, edited, forgotten or re-indexed item's
row is dropped (`knowledge._VectorCache`). It's built from SQLite once, at
start-up, and again only if something marks it dirty (`Index.mark_dirty`),
the safety net for a write it wasn't told about. Measured with 10,000 items
of 768 numbers: a search right after adding a fact took 50 to 170 ms when the
matrix was rebuilt for every change, and about 1 ms now.

The search itself (`Index.search_many`) runs in a worker thread
(`asyncio.to_thread`), so the event loop, and with it the voice and the
bodies, never waits on it. The one SQLite connection is shared across threads
behind the memory's lock, which every read and write already takes.

The message is embedded **once a turn**. The new-topic check
(`Recall.closeness`) embeds it with your last few messages in one batch and
keeps its vector as the turn's query, so `Recall.for_turn` and each of its
searches reuse it; a caller that already has the vector can hand it to
`for_turn` instead. One Ollama round trip a turn, not two.

## Every turn

1. Kit searches for memories relevant to your message, in **one search**
   split by source (`Recall.for_turn`, `Index.search_many`): up to 8 facts or
   day summaries (weighed by how much each matters and how lately you told
   him, see below), up to 4 older conversation snippets, up to 3 entries from
   his own notebook (`memory.own_memories`), so he remembers what he thought,
   not only what you said, and the register entries that fit. The dot product
   over every vector runs once; the word search runs per source, so each part
   is ranked exactly as a search of it alone would be, and thousands of chat
   snippets can't crowd out the one fact.
2. Those go into the prompt with their dates, along with pinned facts, which
   are always there. The prompt tells Kit that newer memories win and never
   to invent one. His own notes are marked as his, so they're never taken for
   facts about you.
3. If you mention something Kit can't see, it can search deeper (the `recall`
   action) and then answer with what it found, or say it doesn't know.
4. The exchange is indexed, so it can be found later. That, and anything to
   learn from the turn (a `remember` action, "Emma's my cousin"), happens in a
   background task after the reply is out (`Brain._learn_later`): the chat
   never waits for the embedding model or the comparison, and a bad night for
   Ollama is logged, not lost. The server cancels the task cleanly on
   shutdown (`Brain.close`). The bodies get a `remembered` life event
   (decision, fact, what it replaced) when it's done, which the desk app shows
   as a note in the chat.

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
passing remark least; the end-of-day pass rates each one 1 to 5). Recall
finds twice as many relevant facts as it needs, then keeps the ones that
matter more and are fresher: each counts from `memory.weight_floor` (0.3) up
to 1, half importance and half how recently you **told Kit or confirmed** it
(halving every 30 days). Pinned facts count fully. A floor of 1 turns the
weighting off.

"Confirmed" is the last time you said it again: when a new fact turns out to
be one Kit already has (the **same** decision below), that fact's `confirmed`
time is set. Otherwise freshness runs from when it was learned, and an
**update** is a new fact, so it starts fresh.

Recency used to run from when a fact was **last recalled**. That looked
natural but fed on itself: the weight is half recency, so a fact that was
recalled once came up fresher next time and was recalled again, while an
equally relevant fact it beat drifted to the floor, and nothing you did could
change the order. Memory systems that work (and people) fade a fact by how
long since it was true or last confirmed, not by how often it was fetched.
Kit still records `last_recalled` on each fact, since it's useful to see, but
it no longer counts.

Two kinds of fact know about time:

- **now**: how things are lately ("Dan's been sleeping badly", "Sarah's away
  this week"). They go after `memory.now_days` (14) and can never be pinned.
- **plan**: something on a date. The date is worked out when it's learned
  ("the dentist on Thursday" said on Tuesday is 8 October) and shown with it,
  and once it's past the prompt says so.

Every item's dates carry the time zone, a day summary's included: it's dated
23:59:59 of its day in the server's zone. Summaries from before this had no
zone; readers take either (`kit.pastimes.parse_time`).

## Learning without making a mess

A memory that only ever adds things fills up with near-copies and stale facts.
So a new fact is compared with the five closest facts Kit already has, and the
local model decides:

- **same:** it's already known, so nothing is added, and the known fact is
  marked confirmed today;
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

In cloud-only routing with the background work in the cloud, the local model
only stands in, and a fact from a chat never wakes it: if the cloud can't
compare the fact, it's simply kept as new (`Learner.learn(local=False)`), and
the night pass, which may load the local model, sorts out any near-copy.

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
at home from any of these. The local model still sees all of it. The phrase is
read once, when the message arrives, and kept as a flag on the message
(`Message.private`) and on the indexed exchange; `Memory.shared` and
`Recall.for_cloud` read the flag. Messages from before the flag were marked
from their words by the migration that added it.

## The spend log

Every cloud call goes in the `spend` table of the same database: when, which
model, the question (cut to 500 characters), the tokens in and out, and the
cost. Three columns say how the prompt cache did: `cached_tokens` (input
tokens read from the cache, at a tenth of the price), `cache_write_tokens`
(written to it, at 1.25 times) and `searches` (web searches the model ran).
`kit memory spend` prints them as `cached 1830/2400`; `/api/spend` returns
them with each row, and `/api/spend/summary` adds each model's cached total.
See [[Models and Routing#Caching]] for why the figure should be high.

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
- `kit memory scrub WORDS... [--since DATE]` is for lines that should never
  have been said, such as testing his bad-night care on the real Kit. It finds
  every message since the date that says any of the words (curly apostrophes
  count), Kit's lines straight after each, and every current item made since
  then that says them or was kept from those messages: recalled exchanges,
  facts, notebook lines, day summaries. It shows them first; `--apply` backs
  up, takes them out, and puts any day already summarised back in the queue so
  it's summarised again without them. Feelings and a bad night aren't touched:
  they fade on their own within hours.
- The memory page and `kit things ...` show the register, with links,
  suggestions to confirm or reject, other names, history and forget.
- The memory page's **Kit's notebook** tab (and `kit life notebook`) shows
  Kit's own notes, journal, self-sheet and quirks, with forget and undo.
- `kit eval memory` measures accuracy on a scratch memory: right fact
  recalled, nothing recalled for unknown things, no stale or duplicate facts.
  Run it after changing models or memory settings.
- `kit eval memory --replay backups/memory-....db` asks your own questions
  (`config/memory-questions.toml`, each with words the right fact contains)
  of a copy of a real memory snapshot, and reports whether the right fact came
  first, further down, or not at all. It's the check for ranking drift: run
  it now and then, and after a change to recall, to see that months of
  recalls, supersedes and new facts haven't buried anything. The snapshot
  itself is never written to.
- Memory is backed up daily to `backups/`, and the database records its
  schema version so future upgrades can migrate it safely.
