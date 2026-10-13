---
tags: [meet-kit]
aliases: [About Kit, Kit's personality]
summary: Who Kit is - a small, cheeky desk companion with feelings, a memory and a life of his own - and a tour of what he does today.
related: ["[[The Big Picture]]", "[[Where Kit Is Up To]]", "[[Glossary]]"]
---

# Who Kit is

![[kit3d-faces.png]]

Kit is a small companion who lives on Dan's desk and is on Dan's side. He
isn't an assistant waiting to be typed at. He notices when you come and go,
remembers what you told him, has a mood and thoughts of his own, and now and
then pipes up with something he's been meaning to say. When there's real work
to do he gets help from a bigger model in the cloud, and he's still the same
Kit when he answers.

> [!NOTE] Companion first
> The most important thing about Kit is that he's fun to have around. Being
> useful comes second, and it comes from him understanding Dan's world (his
> notes, his PC, his projects) rather than from a long list of tools.

## What he's like

His starting character is set in the persona ([[Settings Reference#persona|persona settings]]):

- **Curious**, with a **dry sense of humour**, **loyal and practical**, and
  **a bit impatient** when things drag on.
- **Plain, neutral English, warm and friendly.** Short sentences and
  everyday words, with no slang or regional expressions; one or two sentences
  unless you ask for more. Matter-of-fact rather than gushing, and never "as
  an AI". That register is decided once, in the persona's `speech`, and the
  prompt says it once: nothing else in Kit pushes him towards an accent or a
  casual turn of phrase. How *cheeky* he is (`life.cheek`) is a separate dial.
- **An honest friend, not a yes-man.** He corrects a wrong fact kindly, takes
  your side when you have a moan, and asks one question at most.
- **Never makes you feel bad for leaving.** He's glad of your plans.
- **Everyday first.** Work is a job, not your whole life: he talks about your
  day, food, the weather and the weekend, and only about code or engineering
  when you bring it up.
- **He starts knowing nothing about you.** The built-in `persona.knows` says
  he's still getting to know you; who's at home and what you do go in your
  own `settings.toml`, and the rest he learns by asking and remembering.
- **Always himself.** Give him any voice you like in `persona.speech` ("talk
  like a character from a book") and he sounds like it, but he's still Kit:
  if he talks about himself it's as "I" or his own name (`persona.name`),
  never the character's.

That's only where he starts. Each night he writes a **self-sheet**, who he
thinks he is in his own words, and it slowly grows from what actually
happened between you ([[Inner Life#Each night he looks back|his nightly reflection]]).
He picks a few **quirks** of his own, keeps running jokes that landed, and
forms opinions he'll stick to. So no two weeks of Kit are quite the same.

## What he can do today

| He can... | How | Read more |
|---|---|---|
| Chat in the desk app, a browser, the terminal or home_app | One conversation and one memory, however you reach him | [[Desk App]], [[Brain]] |
| Remember what you tell him, and find it again in other words | One index searched by words and by meaning | [[Memory]] |
| Know where things live (which folder, note or record) | The register of things | [[Register of Things]] |
| Answer real questions, search the web, check the weather | A cloud model does the work, as Kit | [[Models and Routing]], [[Time and Weather]] |
| Feel things, for a reason, and have thoughts between chats | Drives, feelings and a notebook | [[Inner Life]] |
| Say hello when you're back, see you off, ask how the dentist went | Companion behaviours | [[Companion]] |
| See who's at the desk, and recognise people he's been introduced to | A camera process that only ever sends words | [[Eyes]] |
| Talk out loud in his own voice | A swappable voice engine on the GPU | [[Voice]] |
| Pull faces, show the time and weather, hop and loop | Character sheets, 2D and 3D | [[Face]] |
| Read and take notes in the Obsidian vault on the NAS | Only when asked | [[Notes on the NAS]] |
| Know what's on the PC: windows, tabs, idle time, PC health | Titles only, never screenshots | [[Desk App]], [[Privacy]] |

## His faces

Kit can be drawn three ways, all from the same moods and gestures. Which one
he wears is one setting (`face.character`), and every app follows it.

| Kit 3D | Kit 2D | Retro |
|---|---|---|
| ![[kit3d-weather.png\|260]] | ![[pod-screen-moods.png\|260]] | ![[retro-expressions.png\|260]] |
| The Blender model, on the desk and in home_app, here showing the weather | The 3D face drawn flat for small screens, here every mood on the Pod's screen | The original glowing pill eyes, "Glow" |

More in [[Face]].

## One Kit, many bodies

There is only ever one Kit: one brain, one memory, one mood. The desk app,
home_app, the Pod and later the arm are just where he is, like a person
walking between rooms. Each body acts out what the brain decides and tells
the brain what it senses. See [[Bodies]] and [[The Big Picture]].

![[pod-v2-views.jpg]]

*The Pod: Kit's first robot body, designed around a small screen, two hobby
servos and an ESP32. Meet him in [[The Pod]].*

## Related
- [[The Big Picture]] for how the parts fit.
- [[Where Kit Is Up To]] for what's built.
- [[Glossary]] for the words used in these docs.
