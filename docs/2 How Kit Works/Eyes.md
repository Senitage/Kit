---
tags: [how-it-works, eyes]
aliases: [Vision, kit.eyes, Camera, Who's who]
summary: How Kit sees - a camera process beside the webcam that tells the brain who's at the desk and what they're doing, in words and numbers, never pictures.
---

# Eyes

> [!ABSTRACT] In short
> A small program, `kit eyes`, runs on the PC with the webcam. It finds
> people and things, reads faces, hands and poses, and about once a second
> tells the brain **in words and numbers** what it sees: who's at the desk,
> where they are, what they're doing, what just happened. **Never a picture.**
> The brain keeps that as a scene, the way it keeps what's on your PC. People
> you've introduced are recognised by name.

## What it lets Kit do

- **Know you're there** even when you're only reading, so he doesn't doze off.
- **Say hello** when someone sits down after the desk was empty a while, by
  name if he knows them.
- **Look at you**: his face's eyes follow yours, and the Pod turns to you.
- **Notice things**: the cat wandering in, a wave, a thumbs up, a cup in your
  hand. They go into his thoughts, and arrivals and animals into his memory
  (`seen`), so "when did I get in this morning?" has an answer.
- **Have a proper look** when you ask ("what am I holding?") with the
  `look_around` action.

## How it works

```mermaid
flowchart LR
    Cam["Webcam"] --> Det["Detector: people and things, with ids"]
    Det --> Read["Faces, hands, pose"]
    Read --> Rec["Who's who: face numbers"]
    Read --> Act["Actions over a few seconds: waving, nodding, drinking"]
    Rec --> Scene["The scene, in words"]
    Act --> Scene
    Scene -- "POST /api/eyes/scene, once a second" --> Brain["Brain: scene context"]
    Brain --> Life["Inner life: hello, wake, look events"]
    Brain --> Prompt["One line in every prompt"]
```

- **Detector**: YOLO11 finds people and objects, and ByteTrack keeps their ids
  from frame to frame. It runs on the PC's GPU (or CPU).
- **Faces, hands and pose** come from MediaPipe: where someone's looking,
  their expression, hand gestures, body pose.
- **Actions** like nodding, waving, talking and drinking come from a few
  seconds of movement, not one frame.
- **Who's who**: introduce someone with `kit eyes enrol NAME` and a ready-made
  face model keeps a few dozen sets of 128 numbers from their face. No picture
  is kept, and a face can't be rebuilt from the numbers. `kit eyes forget NAME`
  deletes them.
- **Settings come from the brain** (`[eyes]`), so there's one place to change
  them, and running eyes pick changes up.

## The switch

**Let Kit see me** in the desk app's tray menu (or `kit eyes pause`) turns the
eyes off: the camera is released, and Kit is told he can't see, so he never
pretends to. The brain keeps the switch across restarts. See [[Privacy]].

## Try it

```
kit eyes cameras        # which cameras this PC has
kit eyes --show         # a window with boxes, faces and the scene in words
kit eyes                # every day, headless
kit eyes show           # what Kit can see right now, as he's told it
kit eyes enrol me       # introduce yourself; NAME for anyone else
kit eyes faces          # who his eyes know
```

## Go deeper
- [[Vision Stage 1]]: installing the eyes, privacy and the test checklist.
- [[Vision Stage 2]]: introducing people, and how recognition works.
- [[Inner Life]]: what the brain does with arrivals and sightings.

## Under the hood
- `src/kit/eyes/`: the camera side: `camera`, `detect`, `faces`, `body`,
  `actions`, `recognise`, `enrol`, `scene`, `run`, `link`, `preview`.
- `src/kit/scene_context.py`: the brain's side: the latest scene, the day's
  comings and goings, the prompt line and `look_around`.
- `src/kit/known_faces.py`: the people Kit has been introduced to.
