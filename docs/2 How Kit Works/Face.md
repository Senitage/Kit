---
tags: [how-it-works, topic/face]
aliases: [Kit's face, Character sheets, kit.face, Glow]
summary: How Kit's face works - one expression rig, character sheets that say how he looks (Retro, Kit 3D, Kit 2D), shows for the time and weather, and body moves.
related: ["[[Face In Depth]]", "[[Desk App]]", "[[Bodies]]"]
---

# Face

> [!ABSTRACT] In short
> The brain picks an **emotion** and **gestures** for every reply. A
> **rig** turns those into numbers (how open his eyes are, where he looks, how
> his head moves), and a **painter** draws the numbers. What he looks like
> lives in a **character sheet**, one file per character, served by the brain,
> so every app and body draws the same Kit, and a redesign is one new file.

![[kit3d-faces.png]]

## His characters

| Character | What it is | Where it's used |
|---|---|---|
| `retro` | The original **Glow**: two glowing pill eyes on a dark screen | The default; anywhere |
| `kit3d` | **Kit 3D**: the Blender model, with brows, a mouth, blush and props | The desk app and home_app |
| `kit2d` | **Kit 2D**: the 3D face drawn flat in rounded shapes | Small screens like the Pod's |

Pick one with `face.character` (the settings page, or
`kit config set face.character kit3d`). A sheet's `use` table says which look
each app or body draws, so the desk can be 3D while a little robot screen stays
2D, from the same moods and gestures.

![[kit2d-sheet.png]]

*Kit 2D: every mood, next to the 3D face, and on the Pod's 128 x 128 screen.*

## The rig, in three layers

1. **Reflexes**, all the time: blinks, quick eye darts, breathing, and
   looking at something: the mouse, or your face once his [[Eyes]] are on.
2. **The emotion** from each reply sets a pose the face eases into and holds.
   Between replies he rests on his mood ([[Inner Life]]).
3. **Gestures** play a short clip a beat before each sentence's words.

States bend the pose for what's going on between replies: `idle`,
`listening`, `thinking`, `speaking`, `working`, `sleeping` and `offline`.

While he's `speaking`, his mouth follows his voice: the desk app measures how
loud each bit of sound is as it plays and the face opens its mouth to match
(`talk`), so it moves on his words, closes on pauses and stops when the sound
does. With nothing measuring (no voice, a body without the sound), a steady
talking pulse stands in. See [[Voice#How a sentence becomes sound]].

## Emotions and gestures

The brain only ever picks from these names (`src/kit/reply.py`), and every
character must have a pose for each emotion and a clip for each gesture. A
test makes sure.

- **17 emotions**: neutral, happy, curious, thinking, surprised, concerned,
  playful, tired, proud, excited, sad, confused, shy, grumpy, focused,
  relieved, fond.
- **20 gestures**: none, nod, shake, tilt_head, perk_up, droop, look_away,
  shrug, wave, bounce, lean_in, wink, laugh, sigh, startle, yawn,
  double_take, wiggle, peek, look_up.

![[retro-expressions.png]]

*Retro's 17 emotions.*

## Shows for the time, date and weather

Ask Kit the time and his eyes turn into the time; ask the date and they
become "FRI 9 OCT". Ask about the weather and the temperature takes his eyes'
place while the sky plays on and around him: rain, a storm, sun, wind, fog, a
scorcher, or the moon and stars after dark. The brain picks the show from your
words and sends the facts; each body draws it its own way.

![[retro-shows.png]]

![[kit3d-sleep-and-shows.png]]

*Kit 3D's seven-segment clock and weather, and asleep: moon, stars, Zs, and
now and then a dream.*

## Body moves

Gestures move his face within its screen; **body moves** move all of him: a
loop when he's excited, a hop, a double hop, a jump back, a sway, a sink. On
the desk his window travels; on the arm the same names become arm moves. The
Look page's "How much Kit moves" sets how lively he is.

## Kit 3D, live from the brain

Apps don't draw the 3D face themselves. The brain serves a **face page**
(`/face/`, three.js) with the model and its pack, and the desk app lays it
over his window. The page checks the brain every few seconds and reloads when
anything changes, so a new model from Blender or a retuned mood reaches the
desk without a new desk app. `face.pack_folder` can point straight at the
folder Blender writes, for live tuning.

## Go deeper
- [[Face In Depth]]: the character sheet format, Kit 2D's shapes for
  painter ports, 3D packs, shows and moves in full.
- [[Desk App]]: the Look page (eye colour, face size, how much he moves).
- [[Bodies]]: his face on the Pod and the arm.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/face/rig.py`: the expression rig.
> - `src/kit/face/character.py`: loading and checking character sheets.
> - `src/kit/face/characters/`: `retro.json`, `kit2d.json`, `kit3d.json` and the 3D pack.
> - `src/kit/face/body.py`: body moves.
> - `src/kit/face/serve.py`, `src/kit/web/face/`: the 3D face page.
> - `src/kit/shows.py`: picking a show; `src/kit/desk/scenes.py`: drawing it on the desk.
> - `src/kit/desk/glow.py`: the 2D painter; `src/kit/desk/face3d.py`: the 3D overlay.
> - `assets/kit_3d_face/`: the Blender build scripts for Kit 3D.
