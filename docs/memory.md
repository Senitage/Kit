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
   summaries, up to 4 older conversation snippets, and up to 3 entries from his
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

## Learning without making a mess

A memory that only ever adds things fills up with near-copies and stale facts.
So a new fact is compared with the five closest facts Kit already has, and the
local model decides:

- **same:** it's already known, so nothing is added;
- **update:** it changes a fact ("I sold the Hilux, I drive a Ranger now"), so
  the new fact supersedes the old one, which stays in its history;
- **new:** it's about something else, so it's added.

Facts come from two places: "remember that..." in conversation, and the
end-of-day pass, which writes the day's summary and learns its lasting facts.

## You stay in charge

- The memory page (`/memory`) and `kit memory ...` show everything Kit knows,
  grouped by kind, with search, edit, pin, history and forget. Forgetting
  removes a fact and all its earlier versions.
- The memory page and `kit things ...` show the register, with links,
  suggestions to confirm or reject, other names, history and forget.
- The memory page's **Kit's notebook** tab (and `kit life notebook`) shows
  Kit's own notes, journal, self-sheet and quirks, with forget and undo.
- `kit eval memory` measures accuracy on a scratch memory: right fact
  recalled, nothing recalled for unknown things, no stale or duplicate facts.
  Run it after changing models or memory settings.
- Memory is backed up daily to `backups/`, and the database records its
  schema version so future upgrades can migrate it safely.
