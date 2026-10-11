---
tags: [about, docs, conventions]
aliases: [About the docs, Docs conventions, Keeping the docs up to date, Writing docs]
summary: How this vault is laid out, how to open it in Obsidian, the writing conventions, and the checklist for keeping it up to date whenever Kit changes.
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
   Both are bookmarked in the left sidebar.

The **graph view** (`Ctrl+G`) shows every note and link, coloured by layer.
Hover any link to preview it; the backlinks pane shows what links to the
note you're on.

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
| `Templates` | | Starting points for new notes |

Each **How Kit Works** note has the same shape, so you always know where to
look:

1. An **In short** box: the whole idea in a few lines.
2. The middle: how it works, with a diagram or a picture where it helps.
3. **Go deeper**: the deep dive, the guide, the neighbouring notes.
4. **Under the hood**: the source files, for anyone who wants the code.

## Writing conventions

- **One idea per note**, named in plain words in Title Case. Note names are
  unique across the vault, so a link never needs a folder.
- **Links are wiki-links**: `[[Memory]]`, `[[Memory#Finding things]]`,
  `[[Bodies#The Pod|the Pod]]`. Inside a table, escape the alias bar:
  `[[Bodies#The Pod\|the Pod]]`. Don't link to a heading with a colon in it;
  reword the heading instead.
- **Every note starts with properties** (`tags`, `aliases`, `summary`), then
  its title as a `#` heading. The `summary` is one sentence, written for
  someone, or something like Claude, deciding whether to read the note.
- **Guides and reference notes** start with an `Up:` line back to [[Home]].
- **Plain words first.** Short sentences, everyday examples, no jargon in a
  How Kit Works note that the [[Glossary]] doesn't explain.
- **Pictures** go in `Assets/` and are embedded with `![[name.png]]`, or
  `![[name.png|400]]` for a width. Keep them small: PNG for flat drawings,
  JPEG for photos and renders.
- **Diagrams** are Mermaid code blocks. In a flowchart, a node named after a
  note becomes clickable with `class NodeA,NodeB internal-link`.
- **Callouts** for asides: `> [!ABSTRACT] In short`, `> [!TIP]`,
  `> [!NOTE]`.
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
| A pull request opened or merged | [[Where Kit Is Up To]], and [[Roadmap]] when a stage moves |
| A new word | [[Glossary]] |

A new stage brings a guide in `4 Guides` with its setup and test checklist,
named like the others.

## The docs test

`tests/test_docs.py` runs with the rest of the tests (`pytest -q`) and fails
when the vault drifts from the code:

- every wiki-link and `#heading` link points at a note and heading that exist;
- every embedded picture is in `Assets/`;
- note names are unique, and every note has `tags` and a `summary`;
- every `src/...` path a note mentions exists;
- every module in `src/kit` is in [[Code Map]];
- every setting is in [[Settings Reference]], and every `kit` command in
  [[Commands]];
- every `docs/...` path mentioned in the code, `README.md` or `CLAUDE.md`
  exists.

It can't tell whether the words are still true; that part is on whoever
makes the change.

## Templates

`Templates/` holds starting points: **How It Works Note** and **Guide
Note**. In Obsidian, **Insert template** (from the command palette) fills a
new note with one.

## Go deeper
- [[Home]]: the map and every note.
- [[Code Map]]: from the notes into the code.
