---
tags: [how-it-works, topic/memory]
aliases: [How Kit remembers, kit.memory, Knowledge index]
summary: How Kit remembers - one index for everything he knows, searched by words and by meaning every turn, with facts that update instead of piling up.
related: ["[[Memory In Depth]]", "[[Register of Things]]", "[[Stage 1 - Text Brain]]"]
---

# Memory

> [!ABSTRACT] In short
> Everything Kit can recall lives in **one index**: facts about you, a summary
> of each day, every conversation, the register of things, your notes, his
> own thoughts, and what his eyes noticed. Every message, he searches it **by
> words and by meaning** and puts the best matches in front of the model, with
> their dates. New facts are **compared with old ones**, so "I sold the Hilux"
> replaces the old fact instead of sitting beside it. You can see, search,
> pin, edit and forget all of it.

## What's in it

```mermaid
flowchart LR
    subgraph Sources
        F["Facts about you"]
        D["Day summaries"]
        C["Conversations"]
        T["Register of things"]
        N["Your notes"]
        S["His notebook"]
        E["What his eyes saw"]
        Y["Your files"]
    end
    I[("One index: words and meaning")]
    F & D & C & T & N & S & E & Y --> I
    I --> R["Recall, every turn"]
    I --> P["Memory page and kit memory"]
    I --> V["kit eval memory"]
```

| Source | What's in it |
|---|---|
| `memory` | Facts about you, by kind: about you, preferences, projects, places, people, plans, how you've been lately |
| `days` | A summary of each finished day |
| `conversation` | Every exchange, so old chats can be found |
| `things` | The [[Register of Things]] |
| `notes` | Your Obsidian notes, by heading ([[Notes on the NAS]]) |
| `self` | His own thoughts, opinions, moments and journal ([[Inner Life]]) |
| `seen` | Arrivals after a while and animals wandering in ([[Eyes]]) |
| `files` | What's inside the documents in the folders you chose, a page at a time ([[Your Files]]). Searchable now; brought into conversation by the file tools |
| `house` | The lights, switches and rooms Home Assistant shows him ([[The House]]) |

A new kind of thing to remember (photos, projects) is added as a new
source in the same index, and recall, search, the memory page and the
accuracy test all cover it with no other change.

## Finding things

Every search runs two ways at once and merges the results:

- **By words**, with SQLite full-text search: exact names, numbers, file names.
- **By meaning**, with a small embedding model in Ollama: "where's my tax
  stuff?" finds "tax returns are in Documents/Finance/Tax".

A match only counts if it's close enough in meaning (`memory.min_similarity`),
which is what lets him say "I don't know" instead of guessing. If the
embedding model is down he searches by words alone, and catches up later.
Your message goes to the embedding model once a turn: the same vector serves
the new-topic check ([[Brain#Conversations, chats and topics]]) and every search of
the turn.

Among relevant facts, the ones that **matter more** (people, things about
you) and the ones you **told him or confirmed lately** come first, the way a
person's memory works. Being recalled doesn't count for that: a fact that won
once would otherwise keep winning. **Pinned** facts are always in mind.

The whole turn is **one search**: facts and days, old conversation, his
notebook and the register are looked up together and split by source, and it
runs off to the side, so his voice and his bodies never wait on it. The
meaning vectors stay in memory and are kept in step as facts are added,
replaced or forgotten, so a search costs the same at ten thousand memories as
at a hundred.

## Learning without a mess

A new fact is compared with the closest facts he already has, and a model
decides: **same** (nothing added, but the fact counts as confirmed today),
**update** (the new fact supersedes the old, which stays in its history), or
**new**. Facts come from "remember that...", from who someone is to you
("Emma's my cousin"), and from the **end-of-day pass** after midnight, which
writes the day's summary and learns its lasting facts.

Learning happens **after his reply is out**, in the background: a "remember
that" never holds the chat up for the embedding model or the comparison, and
in cloud-only routing the local model isn't woken for one. The bodies are told
what he kept ("Remembered: ...") when it's done.

Two kinds of fact know about time: **now** facts ("been sleeping badly") fade
after two weeks, and **plans** keep their date, so a past one isn't upcoming.

## Keep it local

Say "keep it local" and that message, and everything Kit learns from it, is
marked private and never goes to a cloud model: not in that turn, not in
recall, not in the nightly reflection. See [[Privacy]].

## You stay in charge

- The **memory page** (`/memory`, or Memory in the desk app's window) shows
  everything, grouped by kind, with search, teach, pin, edit, history and
  forget. Forgetting removes a fact and all its earlier versions.
- `kit memory ...` does the same from a terminal ([[Commands#Memory]]).
- `kit memory tidy` sorts what he knows by today's rules, showing the plan
  first.
- `kit memory scrub "can't cope"` takes out lines that should never have been
  said (a test, a joke he took seriously): the messages, his answers, and
  anything he kept of them, showing what would go first.
- Memory is **backed up** daily to `backups/` in the data folder.
- `kit eval memory` checks accuracy on a scratch memory, and `kit eval memory
  --replay` asks your own questions of a backup of the real one, to see the
  right fact still comes first after months of use ([[Evals]]).

## Go deeper
- [[Memory In Depth]]: the full story, every rule and number.
- [[Register of Things]]: facts say what's true; the register says where things are.
- [[Stage 1 - Text Brain]]: setting it up and testing it.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/knowledge.py`: the one index (full-text and vectors, supersede, history).
> - `src/kit/memory.py`: the SQLite file: conversation, facts, days, spend, migrations.
> - `src/kit/recall.py`: what goes into each turn, and the weighting.
> - `src/kit/learning.py`: same, update or new; the end-of-day pass.
> - `src/kit/embed.py`: meaning vectors from Ollama.
