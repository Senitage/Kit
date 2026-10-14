---
tags: [how-it-works, topic/brain]
aliases: [The brain, Conversation loop, kit.brain]
summary: The brain is Kit's conversation loop on the server - every message, pipe-up and thought goes through it, and it answers in one shape whichever model speaks.
related: ["[[Tools and Packs]]", "[[Models and Routing]]", "[[Memory]]", "[[Inner Life]]", "[[API]]"]
---

# The brain

> [!ABSTRACT] In short
> The brain is `kit serve`: one program on the server that holds the
> conversation, his memory and his inner life, and serves the chat page and
> the API. Every message, from any body or page, goes through the same loop
> and gets an answer in the same shape: **words**, an **emotion**,
> **gestures**, maybe an **action**, maybe some **detail** to read. That's
> what lets one Kit live in many bodies.

[[Life of a Message]] follows one message through it, step by step.

## One shape for every reply

Whoever answers, the local model or a cloud model, the reply comes back as
the same thing (`src/kit/reply.py`):

| Part | What it is | Example |
|---|---|---|
| words | What he says, short and spoken | "Morning. Rough one? Coffee first." |
| emotion | One of 17 moods his face eases into | `concerned` |
| gestures | Named moves played a beat before the words | `lean_in`, `nod` |
| action | Something to do before answering again | `recall`, `weather`, `ask_cloud` |
| detail | Something to read on screen, never spoken | code, a list, a link |

The model only ever picks **names** (an emotion, a gesture), never a motion.
Each body turns the names into movement its own way, so the desk app, the Pod
and the arm all understand the same reply. The full list of emotions and
gestures is in [[Face]].

## Two passes when the local model talks

With `ollama.speak_pass` on (the default), the local model answers in two
steps: a quick plan in JSON (emotion, gesture, his **reading** of your
message, action), then his words in plain text at a livelier temperature.
Small models sound stiff when they write speech inside JSON; in plain text
they sound like themselves. His opening is checked against what he said
lately, so he doesn't repeat himself. The speaking step points back at the
notes in the prompt (how he feels, his voice, the asides) rather than
repeating them. Cloud models answer in the same JSON, read as it streams in,
so he starts talking as soon as the first words arrive. More in
[[Inner Life In Depth]], under "Two passes".

## The reading: judgement over keywords

The words of a message only **guess** what it is. Hello, goodbye, news, a
question about Kit himself, a "..., isn't it?", a question about the PC or
the room, a bad-night phrase: each has a table of words that fires as the
message arrives, and shapes the first prompt. Then the model that answers
gives its own reading, in the plan (or a cloud reply): `intent` (chat,
question, request, goodbye, news), `about_kit`, `wants_pc_look`,
`wants_camera_look`, `said_it` (did you actually say the thing he wants to
remember or put in the register) and `crisis_candidate`. Where the model gave
a field, it decides everything after: a `remember` goes ahead on `said_it`,
not on a word count; a note is taken on a `request`, not a phrase; a look at
the PC the words missed still happens; a bad night starts only when the
model agrees ([[Inner Life In Depth#A bad night]]). Where it left a field out
(a small model forgot it, or the one-pass local reply, whose schema has no
room for it), the words decide as before.

## What he can do mid-answer

Looking things up is a **tool loop** ([[Tools and Packs]]): the model asks
for a tool, the brain runs it and hands back the result, and the model
answers from it, up to `tools.hops` times in one turn. A cloud model asks
with its own native tool calls; the local model asks with the `action` field
of its plan, and the brain turns that into the same call. The `core` pack
holds the looks:

| Tool | What happens |
|---|---|
| `recall` | He searches memory for something specific, then answers again |
| `look_at_pc` | He reads the full picture from the desk app: every window, what had focus this hour and today, PC health |
| `look_around` | He reads everything his eyes see: who's at the desk, what they're doing |
| `weather` | He gets the forecast, then answers from the numbers |
| `read_note` | He opens one of your notes and answers from it |

The rest stay **actions** in the reply itself, done once the words are out:

| Action | What happens |
|---|---|
| `remember` | A fact is learned, merging with or updating what he knew |
| `note` | A note you asked for goes into your notes vault |
| `offer_note` | Something sounds worth keeping but you didn't ask, so he offers: "want me to note that?" |
| `thing` | A name goes into the register of things (a suggestion you confirm) |
| `ask_cloud`, `ask_expert` | The question goes up to the work or expert model. With `routing.confirm_expert` he asks before calling the expert |

If a cloud model can't answer (offline, no key, budget used up), the local
model answers instead and says why.

## Where you're talking from

Every message says which way it came in (`src/kit/channels.py`), and Kit is
told on each turn:

| Channel | Kit is told | So he |
|---|---|---|
| `desk` | you're typing in the desk app | takes "this" to mean what's on screen |
| `voice` | you're talking out loud at the desk | keeps it short and spoken |
| `phone` | you're on your phone, probably out | keeps it short; doesn't assume you can see the PC |
| `web` | you're on the chat page | answers as usual |
| `home` | you're on his page in home_app | answers as usual |
| `terminal` | you're in `kit chat` | answers as usual |

It's one conversation and one memory whichever way you talk. Each message is
stored with its channel, so a message from your phone shows as "(from their
phone) ..." when you pick up at the desk.

A message can also say it was **said out loud** (`spoken`), so he keeps it
short whatever the channel, and **when it was written** (`sent_at`), for one
that waited on the phone while he was out of reach: if that's more than a
couple of minutes ago he's told so, and that it may be old news. See
[[Phone App#What a message carries]].

## Conversations, chats and topics

- **One conversation**, shared by every way in. The model sees the last
  `brain.history_messages` (20) messages.
- **A long quiet** (`brain.new_chat_after_minutes`, 2 hours) is a hint, not a
  cut: your message is marked "(3 hours later)" and he picks up one thing from
  last time ([[Companion]]), but the conversation carries on, so a reset after
  dinner no longer makes him forget what you were just doing. `kit new-chat`
  (and the desk app's New chat) still starts fresh by hand.
- **A new topic** (a message far in meaning from your last few,
  `brain.new_topic_below`) gets a note beside it saying you've changed the
  subject; the conversation is kept.
- **Settings are read every turn**, so a change on the settings page applies
  from the next message, with no restart.

## Talking while he works

A turn runs as its own task. While a cloud model works on something slow,
you can keep talking: the local model answers meanwhile, told what's in
progress, for how long, and what's been done so far. The slow answer arrives
when it's ready, even if the page that asked has closed. `/api/status` lists
it under `working_on`.

## One voice, two asides at most

Everything the model is told about how Kit sounds is said once: his voice
(the persona's `speech`, plain neutral English), with one line saying it beats
every other note on how he talks (his self-sheet, the example lines, his mood,
his quirks). The example lines are for the tone; his mood and how cheeky to be
(`life.cheek`) come as one sentence with this turn's part. Nothing is repeated
"above all" at the end, and nothing says "not a help desk": a model given the
same instruction eight ways drops one of them, and which one varied. The only
reminder outside the system prompt is in the local model's second pass, where
a small model's words are made ([[Inner Life In Depth#Two passes: deciding, then talking]]).

An **aside** is a stage direction that rides beside your message in square
brackets: the answer to something he piped up with, a hello when you're back,
a bedtime nudge, "you're telling me something, not asking", picking up one
thing from last time after a long quiet, a hint that the subject changed, your answer to a getting-to-know-you question, or
staying with you on a bad night. One message can earn several, each wanting a
different thing from a reply of one to three sentences, so **at most two go**,
the best-ranked: a bad night first, then answering a pipe-up, then a hello,
then one of the rest (bedtime, news, the opener, the interview, and last the
new-subject hint). What the message is itself about (a goodbye, a question
about himself, a fact to check, words that may mean a hard time) always goes. The ones left out aren't lost: a bedtime nudge is owed once
either way, and a hello that isn't said is still in how he feels.

When a model reads how you seem (`dan_mood`, `about`, `for_whom`, `expected`,
and `brought_up` for what on his mind a reply brings up), the prompt says
those fields are notes for himself, never said: their names are English words
a model could otherwise echo. See [[Inner Life In Depth#Reading how you are]].

## Beyond answering

The brain also runs Kit's **heartbeat** (drives, fidgets, pipe-ups and
thoughts), the **nightly upkeep** (day summaries, reflection, backups) and the
**notes sync**. See [[The Big Picture#How the brain keeps time]].

## Go deeper
- [[Tools and Packs]]: the loop behind the looks, and how packs plug in.
- [[Models and Routing]]: who answers.
- [[Memory]]: what gets recalled.
- [[Inner Life]]: what colours the answer.
- [[API]]: the routes the bodies and pages call.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/brain.py`: the conversation loop, the tool loop, actions, pipe-ups, thoughts.
> - `src/kit/tools/`: the tools he can call and the packs they come in.
> - `src/kit/prompt.py`: what the model sees each turn.
> - `src/kit/reply.py`: the reply shape, the plan and its reading fields, emotions and gestures, the streaming reader.
> - `src/kit/local_model.py`, `src/kit/cloud.py`: talking to the models.
> - `src/kit/channels.py`: where you're talking from.
> - `src/kit/server.py`: the app and the background loops; the pages and the API are in
>   `src/kit/routes/`, one file per part of Kit.
