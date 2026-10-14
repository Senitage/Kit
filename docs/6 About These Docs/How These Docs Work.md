---
tags: [about, topic/docs, topic/conventions]
aliases: [About the docs, Docs conventions, Keeping the docs up to date, Writing docs]
summary: How this vault is laid out, how to open it in Obsidian, the writing conventions, and the checklist for keeping it up to date whenever Kit changes.
related: ["[[Code Map]]"]
---

# How these docs work

Up: [[Home]]

These docs are an **Obsidian vault**: a folder of plain markdown notes that
link to each other. They read fine on GitHub or in any editor, and best in
Obsidian, where the links, the graph, the map and the pictures all come
alive.

## Opening the vault

1. Install [Obsidian](https://obsidian.md) (free).
2. **Open folder as vault**, and pick the `docs` folder of your copy of the
   repo.
3. If Obsidian asks, trust the vault so its look (the `kit` CSS snippet)
   switches on.
4. Start at **Home**, or open **Kit Map** for the whole of Kit on one canvas.
   Both are bookmarked in the left sidebar, with **All notes**, **Running
   Kit**, and groups for how Kit works, the Pod and the reference shelf.

## What Obsidian adds

Everything below is plain markdown underneath, so the notes still read on
GitHub; Obsidian just brings it to life.

| Feature | Where to find it | What it gives you |
|---|---|---|
| **Graph view** | `Ctrl+G` | Every note and link, coloured by layer; the Pod's notes in orange |
| **Kit Map** canvas | `Kit Map.canvas` | The whole of Kit on one board: cards open their notes, with pictures |
| **All notes** base | `All Notes.base`, also at the bottom of [[Home]] | Every note and its summary as a live table, with tabs: by layer, how Kit works (as cards), guides, deep dives, reference, the Pod |
| **Properties** | The properties panel (right sidebar) | Each note's `summary`, `tags`, `aliases` and `related` (read next) |
| **Hover previews** | Hover any link | A peek at the note without leaving the one you're on |
| **Backlinks and outgoing links** | Right sidebar | What links here, and where this note leads |
| **Embeds** | `![[Pod In Depth#Wiring]]` in [[Building the Pod]] | A section shown live inside another note, so it's written once |
| **Folded callouts** | **Under the hood** at the end of each How Kit Works note | The code paths stay out of the way until you open them |
| **Kit's callouts** | `> [!kit]` on [[Home]] | Kit talking, in his mint glow (the `kit` CSS snippet) |
| **Clickable diagrams** | The map on [[Home]] | Boxes named after notes open them |
| **Nested tags** | The tags pane | Layer tags (`how-it-works`, `guide`, ...) and `topic/...` tags, folded under `topic` |
| **Search by property** | `Ctrl+Shift+F`, then `[summary:memory]` or `tag:#topic/pod` | Find notes by what they're about |

## The layers

| Folder | For | Reads like |
|---|---|---|
| `1 Meet Kit` | Anyone | Who he is, where he's up to, the plan |
| `2 How Kit Works` | Anyone curious | One part of Kit each, in plain words, no code needed |
| `3 Deep Dives` | Anyone changing that part | The full detail behind a plain-words note |
| `4 Guides` | Whoever runs Kit | Step-by-step setup, updating, and each stage's test checklist |
| `5 Reference` | Looking something up | Commands, settings, API, evals, the code map, the glossary |
| `6 About These Docs` | Whoever writes them | This note |
| `Assets` | | Pictures |
| `Home.md`, `Kit Map.canvas`, `All Notes.base` | Everyone | The front door, the map, and every note as a table |
| `Templates` | | Starting points for new notes |

Each **How Kit Works** note has the same shape, so you always know where to
look:

1. An **In short** box: the whole idea in a few lines.
2. The middle: how it works, with a diagram or a picture where it helps.
3. **Go deeper**: the deep dive, the guide, the neighbouring notes.
4. **Under the hood**: a folded callout with the source files, for anyone
   who wants the code.

## Writing conventions

- **One idea per note**, named in plain words in Title Case. Note names are
  unique across the vault, so a link never needs a folder.
- **Links are wiki-links**: `[[Memory]]`, `[[Memory#Finding things]]`,
  `[[Bodies#The Pod|the Pod]]`. Inside a table, escape the alias bar:
  `[[Bodies#The Pod\|the Pod]]`. Don't link to a heading with a colon in it;
  reword the heading instead.
- **Every note starts with properties** (`tags`, `aliases`, `summary`, and
  `related` where it has neighbours), then its title as a `#` heading. The
  `summary` is one sentence, written for someone, or something like Claude,
  deciding whether to read the note. `tags` has the note's layer
  (`meet-kit`, `how-it-works`, `deep-dive`, `guide`, `reference`) and what
  it's about as `topic/...`. `related` lists the notes to read next, as
  links: `related: ["[[Pod In Depth]]", "[[Bodies]]"]`.
- **Guides and reference notes** start with an `Up:` line back to [[Home]].
- **Plain words first.** Short sentences, everyday examples, no jargon in a
  How Kit Works note that the [[Glossary]] doesn't explain.
- **Pictures** go in `Assets/` and are embedded with `![[name.png]]`, or
  `![[name.png|400]]` for a width. Keep them small: PNG for flat drawings,
  JPEG for photos and renders.
- **Diagrams** are Mermaid code blocks. In a flowchart, a node named after a
  note becomes clickable with `class NodeA,NodeB internal-link`.
- **Callouts** for asides: `> [!ABSTRACT] In short`, `> [!TIP]`,
  `> [!NOTE]`, `> [!WARNING]`. A `-` after the type folds it shut:
  `> [!example]- Every mood`. Kit's own: `> [!kit]` when he's talking and
  `> [!under-the-hood]-` for code paths.
- **Write it once.** To show a table or section from another note, embed it
  (`![[Pod In Depth#Wiring]]`) rather than copying it.
- **Code paths** in backticks, from the repo root: `src/kit/brain.py`.

> [!WARNING] This repo is public
> No real addresses, places, network details (IP addresses, host names, home
> paths) or names of Dan's family, friends or pets, in notes or in pictures.
> Use made-up examples: Richmond, NSW for a town, `192.168.1.50` for the NAS.
> Check every screenshot before it goes in `Assets/`.

## When you change Kit

The docs are part of the change. Whoever changes Kit, a person or Claude,
updates the matching notes **in the same pull request**:

| You changed | Update |
|---|---|
| How a part of Kit behaves | Its **How Kit Works** note, and its deep dive if it has one |
| Something you set up, install or test | The stage's guide, or [[Updating Kit]] |
| A setting | [[Settings Reference]] (from `src/kit/settings.py`) |
| A `kit` command | [[Commands]] |
| An API route or event | [[API]] |
| A module added, moved or removed | [[Code Map]] |
| An eval | [[Evals]] |
| A new part of Kit | A new How Kit Works note from the template, linked from [[Home]], [[Kit Map.canvas\|Kit Map]] and its neighbours |
| How he looks | Fresh pictures in `Assets/` |
| A pull request opened or merged | [[Where Kit Is Up To]] (`kit docs check` spots a row left open after it landed), and [[Roadmap]] when a stage moves |
| A new word | [[Glossary]] |
| The Pod's program, printed parts or wiring (`pod/`) | [[The Pod]], [[Pod In Depth]], [[Building the Pod]] |
| How to start, stop or restart something | [[Running Kit]] |

A new stage brings a guide in `4 Guides` with its setup and test checklist,
named like the others.

## The docs test

`tests/test_docs.py` runs with the rest of the tests (`pytest -q`) and fails
when the vault drifts from the code:

- every wiki-link and `#heading` link points at a note and heading that exist;
- every embedded picture is in `Assets/`;
- note names are unique, and every note has `tags` and a `summary`;
- every `src/...` or `pod/...` path a note mentions exists;
- every embedded view of a base (`![[All Notes.base#Guides]]`) exists;
- every module in `src/kit` is in [[Code Map]];
- every setting is in [[Settings Reference]], and every `kit` command in
  [[Commands]];
- every `docs/...` path mentioned in the code, the Pod's files, `README.md`
  or `CLAUDE.md` exists.

It can't tell whether the words are still true; that part is on whoever
makes the change.

## Templates

`Templates/` holds starting points: **How It Works Note** and **Guide
Note**. In Obsidian, **Insert template** (from the command palette) fills a
new note with one.

## Go deeper
- [[Home]]: the map and every note.
- [[Code Map]]: from the notes into the code.
