---
tags: [how-it-works, topic/bodies]
aliases: [Robot bodies, The arm, One brain many bodies]
summary: One brain, many bodies - how the desk app, home_app, the Pod and later the arm all act out the same Kit, and what each body is.
related: ["[[The Pod]]", "[[Phone App]]", "[[Pod In Depth]]", "[[Building the Pod]]", "[[Inner Life In Depth]]", "[[Face In Depth]]", "[[Roadmap]]"]
---

# Bodies

> [!ABSTRACT] In short
> There's only ever one Kit: one brain, one memory, one mood. A **body** is
> just where he is, like a person walking between rooms. Every body listens to
> the brain's events and acts them out its own way, and tells the brain what
> it senses. The brain never moves into a robot; a body only adds reflexes,
> like blinking. The desk app is his first body, the **Pod** is his first
> robot, and the **arm** comes last.

## How a body works

```mermaid
flowchart LR
    Brain["Brain: decides moods, sleep, replies, pipe-ups"]
    Brain -- "events: mood, fidget, react, sleep, wake, look, pipe_up, remembered" --> Desk["Desk app"]
    Brain -- "the same events" --> Home["home_app's Kit page"]
    Brain -- "the same, as plain lines" --> Pod["The Pod"]
    Brain -- "later" --> Arm["The arm"]
    Desk -- "what's on the PC" --> Brain
    Pod -- "pats on the head" --> Brain
```

- Bodies listen to `GET /api/life/events`: fidgets, reactions, sleeping and
  waking, mood changes, pipe-ups, what he remembered after a reply
  (`remembered`), and `look` events saying where the person his
  eyes see is. See [[API]].
- Each body draws his face from the same **character sheet**, picking the look
  its `use` table names (`desk`, `home_app`, `robot`). See [[Face]].
- Each body plays the same **gestures** and **body moves** by name, scaled to
  what it can do.
- A body can **say hello** when it starts (`POST /api/bodies/hello`) with what
  it can do, and the brain answers with what *it* can do, so each side only
  uses what the other has. The brain keeps a list of the bodies it has heard
  from and when Dan last used each one. Each PC running the desk app is a body
  of its own. See [[Phone App#Saying hello]].
- **One voice at a time.** When he pipes up, one body says it out loud: the PC
  Dan's using; else the device he last talked through, like his phone while
  he's out; else the PC he was last on. The rest only show the words. See
  [[Desk App#What Kit learns from the PC]].

## The desk app

His body on the Windows PC: a floating face, a chat, a voice. See [[Desk App]].

## home_app

Dan's home website has a Kit page: his face (2D or the 3D page, proxied from
the brain), how he's feeling, and a chat on the `home` channel. It reads the
same events and sheet as the desk. See [[Other Apps]].

![[home-app-panel.jpg|420]]

## The Pod

Kit's first robot: a small printed desk Pod with the whole front as his face.
A 1.5" screen shows **Kit 2D**, two hobby servos **turn and tilt** his head,
an **ESP32** runs it over Wi-Fi, and a touch pad on top feels a **pat**. It
reads the brain's **body feed**, plain lines like `emotion happy`, so a small
board can act Kit out without a JSON library. Its program and print files are
in the repo under `pod/`. See [[The Pod]].

| | |
|---|---|
| ![[pod-v2-hero.jpg]] | ![[pod-v2-inside.jpg]] |
| The Pod | Inside: screen, tilt servo, turn servo, ESP32 |

His neck stays calm: the face is as lively as on the desk, but the head only
moves for a glance round the room, something catching his eye, a real gesture
or his mood's posture. Fidgets stay on the screen.

> [!NOTE] In progress
> The brain's side of the Pod (the body feed, pats, and Kit knowing who in the
> room can hear him) is pull request #36. Next: a speaker and microphone in
> the Pod, so he can talk and listen in the room, one voice at a time.

## The phone

Kit on Android: the body that goes out of the house with you, with his face
at the top of the chat, his voice, and notifications for his pipe-ups. It
pairs with a token of its own. See [[Phone App]].

## The arm

The last stage: Kit in a desk robot arm, with his face on a small screen in
its head and the brain still on the server. A Raspberry Pi at the arm runs the
motors and, later, his eyes. Recorded moves are scaled by his mood and a
little noise, so no two look the same.

![[arm-concepts.png]]

*Four directions explored for the arm. Nothing is decided yet.*

| Kit's state | On the screen now | On the arm later |
|---|---|---|
| Asleep, you're away | eyes close, slides down the screen | lies down flat, slow breathing |
| You come back | startles, perks up | lifts its head, stretches, turns to you |
| Bored | sighs, looks around | taps the desk, peers at things |
| Curious | peeks at your window | leans toward the monitor, tilts its head |
| Sulky | sighs, looks away | turns away a little, droops |

## Go deeper
- [[The Pod]], [[Pod In Depth]] and [[Building the Pod]]: Kit's first robot.
- [[Inner Life In Depth]], under "One brain, many bodies" and "The arm".
- [[Face In Depth]], under "On the arm" and Kit 2D's shapes for painter ports.
- [[Roadmap]]: when each body comes.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/life.py`: the events every body hears.
> - `src/kit/face/body.py`: body moves by name.
> - `src/kit/face/characters/kit2d.json`: the `kit2d_screen` look the Pod draws.
> - `src/kit/desk/alive.py`: how the desk acts out sleep, waking and glances.
