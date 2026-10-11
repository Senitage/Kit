---
tags: [guide, stage, topic/companion, topic/voice, topic/eyes]
aliases: [stage-companion-4, Voice and eyes carry it]
summary: Companion stage 4 - his voice and eyes carry him - cloud answers that start talking at once, sounds in his voice, his face keeping time with it, a backup voice, small moments his eyes feel, and keeping quiet while you're on your phone - with its settings and test checklist.
related: ["[[Companion]]", "[[Voice]]", "[[Eyes]]", "[[Inner Life In Depth]]"]
---

# Companion stage 4: his voice and eyes carry it

Up: [[Home]] · Guides · [[Companion]]

The fourth stage of the companion plan. Stages 1 to 3 gave Kit a life and
feelings; this one lets you feel them without reading a word:

- **A cloud answer starts talking at once.** Claude's answer comes in as it's
  written, so he starts saying the first words (in the answer's mood) within
  about a second, not after the whole answer. Goodbyes are still checked
  whole first, so a goodbye never has a question in it.
- **Sounds in his voice.** With Chatterbox Turbo, a joke gets a chuckle inside
  the punchline, a let-down gets a sigh, a shock a gasp. At most one every
  other sentence, so it stays rare.
- **His face keeps time with his voice.** His mouth moves for exactly as long
  as each sentence plays, not a guess from the words, and each gesture lands
  as its words start.
- **A backup voice.** If his voice runs out of graphics card memory or can't
  start, he switches to Kokoro on the CPU and keeps talking. `kit speech bench`
  says whether an engine fits the card.
- **He feels what his eyes catch.** Wave and he waves back. A thumbs up makes
  him proud. Smile at him for a couple of seconds and he brightens. A frown that
  stays makes him sympathetic. Your eyes closing late at night makes him yawn,
  and bed is on his mind an hour sooner.
- **He doesn't talk over you.** On your phone or talking to someone, he keeps
  quiet, and his bubble says so ("keeping quiet, you're on your phone").
  Whatever he wanted to say can wait till you're done, and then he says why he
  waited ("didn't want to interrupt, but...").
- **Nobody there, nothing said out loud.** If his eyes see nobody at the desk,
  a pipe-up shows on screen instead of being said to an empty room.

How it works is in [[Voice]], [[Eyes#Moments he feels]] and
[[Inner Life In Depth#Busy and held pipe-ups]].

## 1. Update and restart Kit

Update and restart Kit as in [[Updating Kit]]. There are no new packages,
models, keys or memory upgrade.

**The desk app** needs this update too: the sounds, his face keeping time
with his voice, and the "keeping quiet" bubble come with it.

## 2. Settings

As in the earlier stages, the new behaviour is off by default, with three
exceptions that only make him better mannered or quicker:

| Setting | Default | Try | What it does |
|---|---|---|---|
| `cloud.stream` | **true** | true | Claude's answers come in as they're written, so he starts talking sooner |
| `speech.sounds` | false | true | A chuckle, sigh or gasp in his voice (Chatterbox Turbo only) |
| `speech.fallback` | (none) | kokoro | The voice he switches to if his usual one fails |
| `life.eyes_manners` | **true** | true | No pipe-ups while you're on your phone or talking to someone |
| `life.hold_pipe_ups` | false | true | What he wanted to say waits till you're done (up to half an hour) |
| `life.seen_feelings` | false | true | He feels what his eyes catch: waves, thumbs, smiles, frowns, sleepy eyes |

Leaving a pipe-up on screen when his eyes see nobody, and his face keeping
time with his voice, are always on.

To turn the lot on:

```
kit config set speech.sounds true
kit config set speech.fallback kokoro
kit config set life.hold_pipe_ups true
kit config set life.seen_feelings true
kit config set life.dials true
```

`life.dials` is from [[Companion Stage 3]]; the smile test below needs it, so
his face can brighten.

## 3. Check the graphics card first

With a chat or two done (so everything Kit keeps on the card is loaded), run:

```
kit speech bench --engines chatterbox-turbo kokoro
```

Each engine's line ends with a verdict: **fits the graphics card** (at most
about 7.5 of 8 GB used at the peak) or **too tight**. If Chatterbox Turbo is
too tight, use Kokoro (`kit speech use kokoro`), or keep Turbo with
`speech.fallback` set so he switches the moment the card runs out. One of the
lines has a chuckle in it: listen to it on the bench page to hear how Turbo
does sounds.

## 4. Test before moving on

- [ ] **Bench.** `kit speech bench` shows Chatterbox Turbo fitting the card, or
      `speech.fallback` is set to kokoro.
- [ ] **Chuckle.** With `speech.sounds` on, get him laughing at something
      (tell him you burnt the toast again). The chuckle comes inside the
      punchline, not at the start of the reply, and his mouth stops moving when
      the sound stops.
- [ ] **Ask Claude.** In cloud-only routing, ask something that takes Claude a
      few sentences. He starts speaking within about a second, in the answer's
      mood. Then say goodbye: the goodbye is still one warm line with no
      question.
- [ ] **Smile.** With `seen_feelings` and `dials` on, smile at the camera for
      two seconds. Glow brightens and gives a little wiggle; `kit life` shows
      him pleased because you smiled at him.
- [ ] **Wave and thumbs up.** Wave: he waves back. Thumbs up: a nod, and
      `kit life` shows him proud.
- [ ] **Phone in hand.** Pick up your phone while he's bored enough to pipe
      up. He keeps quiet, and his bubble says "keeping quiet, you're on your
      phone". The tray tooltip says the same.
- [ ] **Held.** With `hold_pipe_ups` on, stay on your phone a few minutes while
      he's keen to say something (his bubble says he's saving something). Put
      it down: within a minute he says it, opening with why he waited.
- [ ] **Nobody there.** Step away from the camera while the PC's still awake
      and poke him (`POST /api/life/poke`, or wait for a pipe-up). The line
      shows in the chat, but he doesn't say it out loud.
- [ ] **Backup voice.** With `speech.fallback kokoro`, stop Chatterbox from
      starting (for example, point `speech.engines.chatterbox-turbo.python` at
      a path that doesn't exist). He talks in Kokoro, and
      `GET /api/speech` shows `using: kokoro` and why. Put the setting back and
      he's on Turbo again.

## If something's off

- **No sounds.** They only come with Chatterbox Turbo, and only where a
  sentence's gesture is a laugh, sigh, startle or double take.
- **He goes quiet too often.** The eyes may be reading chewing or singing as
  talking. `kit config set life.eyes_manners false` turns the manners off;
  tell me what `kit life` said he was keeping quiet for.
- **A smile doesn't register.** He only counts a smile while you're facing the
  camera, held for two seconds, and only from you (or the one person in view
  his eyes can't name).
- **Stuck on the backup voice.** He stays on it until his speech settings
  change; any `kit speech` or `kit config set speech...` change gives his usual
  voice another go.
