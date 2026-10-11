---
tags: [how-it-works, memory]
aliases: [Things, kit.things, Tag register]
summary: The register of things - one entry per person, pet, vehicle, place, project or piece of equipment, with where each one lives in every system.
---

# Register of things

> [!ABSTRACT] In short
> Facts say what's true; the register says **where things are**. Like a
> plant's tag register, it has one entry per person, pet, vehicle, place,
> project or piece of equipment, with its other names and a link to where it
> lives in each system. When a message names a thing, Kit sees its entry, so
> "where's the rego for the ute?" goes straight to the right NAS folder.

## An entry

| Field | Example |
|---|---|
| Name and other names | Hilux, "the ute" |
| Kind | person, pet, vehicle, place, project, equipment, other |
| A few words about it | Dan's work ute |
| Links, one per system | `nas`: Documents/Cars/Hilux, `obsidian`: Cars/Hilux, `home_assistant`: garage |

The systems a link can point into: Home Assistant (area or entity), home_app
(record), the NAS (folder), MetTools (folder), Obsidian (note) and code
(project folder).

## How it's used

- **Every turn**, things named in the message come first, then the closest
  entries by words and meaning, up to `memory.relevant_things` (5). They go
  in the prompt as "Things you know and where they live".
- **New names** become suggestions: "we got a puppy called Biscuit, his
  photos are in Photos/Biscuit" gets "want me to add Biscuit?". Say yes, use
  the Add button in the chat, or confirm it on the memory page.
- **Corrections stick**: "no, it's in Tax/2023" replaces that link and keeps
  the old one in the entry's history.
- **While you're away**, thinking about someone or something in the register
  is one of his pastimes ([[Inner Life]]).
- **Stage 4** will use the links to know which app to ask
  ([[Roadmap]]).

Entries are items in the same index as everything else ([[Memory]]), so
they're found by words and by meaning, and every change is a new version.

## Try it

```
kit things list
kit things add Hilux --kind vehicle --alias ute --link nas=Documents/Cars/Hilux
kit things link 12 nas Tax/2023
kit things suggestions
kit eval routing      # do questions bring back the right entry and place?
```

## Go deeper
- [[Memory In Depth#The register of things]]
- [[Stage 1 - Text Brain]]: the test checklist, and your own routing questions.

## Under the hood
- `src/kit/things.py`: entries, suggestions, links and history.
- `src/kit/recall.py`: how entries reach each turn.
