---
tags: [how-it-works, topic/inner-life]
aliases: [Life, kit.life, Drives and feelings, Mood]
summary: Kit's inner life - drives that rise and fall, a mood and feelings with reasons, private thoughts, a notebook, piping up with manners, and a nightly look back that slowly changes him.
related: ["[[Inner Life In Depth]]", "[[Companion]]", "[[Side Stage - Inner Life]]"]
---

# Inner life

> [!ABSTRACT] In short
> Kit isn't scripted. He has a few **drives** (boredom, curiosity, wanting a
> chat, something to say, energy) that rise and fall on their own. From them
> comes a **mood**, and things that happen give him **feelings with a
> reason**. Between conversations he has **thoughts** of his own and keeps
> them in a **notebook**. When a want gets strong enough he **pipes up**, with
> manners. Each night he **looks back** on his day and rewrites who he thinks
> he is, so he grows a little every day.

![[desk-mood-page.png]]

*The Mood page in the desk app: his face, his mood, how he feels and why, and
his needs as bars. It only looks; nothing here can set them.*

## Drives and mood

| Drive | Rises when | Falls when |
|---|---|---|
| Boredom | nobody talks to him, faster while you're at the PC | you talk to him, or he pipes up |
| Curiosity | you open an everyday app or site he hasn't seen today | it fades over a few minutes |
| Wanting a chat | hours pass without a conversation | you talk |
| Something to say | he thinks of something to tell or ask you | he says it |
| Energy | follows the clock: sleepy late, a dip after lunch | sleep restores it |

Out of these comes his **mood**: content, bored, curious, lonely, sleepy, or
sulky after being ignored (a sulk passes by itself in forty minutes, and he
forgets being ignored within the hour). Every half minute he may **fidget** (a sigh, a
look around, a peek) with a gesture that suits it. His mood is also the face
he wears between replies.

## Feelings, with a reason

Things that happen make him feel something, and he knows why: called a legend,
he's **chuffed**; you're stressed, he's **a bit worried about you**; ignored,
he's **a bit put out**. A feeling colours what he says and how he fidgets,
then fades. Ask how he's feeling and he can tell you why. With
`life.mixed_feelings` he can feel two things at once, and with
`life.read_mood = meaning` the model reads how you are from what you mean,
not only your words. With `life.seen_feelings` his eyes count too: a smile
at him, a wave, a thumbs up or a frown that stays ([[Eyes#Moments he feels]]).

## Thoughts and his notebook

Every few minutes while you're around, and sooner when something happens,
he has a **private thought**: something he noticed, a question, an opinion
forming, a joke he's saving. A thought can become something he **wants** to
bring up, change how he **feels**, or become an **opinion**. Ask "what are you
thinking about?" and you get the real one.

His **notebook** is his own, separate from facts about you: thoughts,
opinions, wants, threads in your life, running jokes, moments, a daily
journal, his self-sheet, what's going on with you, and his quirks. It's on
the memory page's notebook tab, where you can forget any of it.

## Piping up, with manners

When a want gets strong enough he says something of his own accord, written
fresh by the model from what you're doing and what he's been thinking. He
never pipes up in quiet hours (10 pm to 7 am), on a call, while his eyes see
you on your phone or talking to someone, while you're typing, when you're
away, right after a chat, or more than a few times an hour. With
`life.hold_pipe_ups` what he wanted to say waits till you're free (and for the
same manners), and he says why he waited (then he isn't "butting in", whatever
the keyboard says). Something he means to bring up later ("ask me tomorrow")
stays in his notebook, out of his prompts, until it's due.
Ignore him and he sulks a little and waits longer next time; being on a call
or your phone isn't ignoring him. On a bad night he's never bored or curious at
you: he checks in once, gently, and otherwise waits for you. Say **"shush"**
or **"not now"** and he's quiet for an hour. `life.chattiness` turns him up
or down.

## Asleep and awake

When you've been away `life.sleep_after_minutes` (or the PC is locked), he
dozes off. He also naps when he's bored and ignored, and turns in himself past
bedtime. A message, you coming back to the PC, or his own body clock wakes
him; his eyes never do, and they shut (models unloaded) while he sleeps. The
brain decides; every body acts it out. Details: [[Inner Life In Depth#Sleep, naps and waking up]]. While you're out he can keep himself busy (watching the
weather, rereading his journal) before dozing: see [[Companion#While you're out]].

## Each night he looks back

After midnight, once the day's summary is written, the expert model reads the
day **as Kit** and writes:

- a **journal** entry, in his own words;
- his **self-sheet**: who he is, how he talks, how you two get on, under 180
  words. It stands in for the persona's traits from then on, so he grows a
  little each day, around the persona and never away from it;
- his **quirks** (at most one change a night), up to three **opinions**, two
  **moments**, things to **bring up tomorrow**, **what's going on with you**,
  new **threads** and **running jokes**.

Once a week a review checks how he's changed. You can undo any of it: go back
to an earlier self-sheet, take a quirk away or give it back.

## Why he stays unpredictable

Wants, not actions; the model writes the words each time; gestures are a
vocabulary he picks from; quirks he chose himself; hidden state (mood,
feelings, sulks, what he's been thinking); and a self he rewrites nightly.
The same moment on a different day gives a different Kit.

## Try it

```
kit life            # mood, feelings and why, drives, thoughts, wants, quirks
kit life notebook   # his self-sheet, journal, thoughts and opinions
kit life think      # a thought now
kit life poke       # make him pipe up now
kit life reflect    # look back on today so far (a few cents)
```

## Go deeper
- [[Inner Life In Depth]]: every drive, feeling, rule and setting.
- [[Companion]]: what he does with all this when you come and go.
- [[Side Stage - Inner Life]]: setting it up, costs, and picking his voice.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/life.py`: drives, mood, feelings, sleep, manners, the events bodies hear.
> - `src/kit/thinking.py`: his private thoughts.
> - `src/kit/notebook.py`: his notebook.
> - `src/kit/reflection.py`: the nightly look back and the weekly review.
> - `src/kit/desk/mood.py`: the Mood page.
