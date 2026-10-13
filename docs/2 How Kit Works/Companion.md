---
tags: [how-it-works, topic/companion]
aliases: [Kit as a companion, Hellos and goodbyes]
summary: What makes Kit a companion rather than a chat window - he knows you were gone, says hello and goodbye well, follows your life, has a life of his own while you're out, and cares on a bad night.
related: ["[[Inner Life In Depth]]", "[[Memory]]"]
---

# Companion

> [!ABSTRACT] In short
> A chat window waits to be typed at. Kit lives on the desk. He knows how long
> you were gone, is glad when you're back, sees you off without guilt, asks
> how the dentist went, gets to know you a question at a time, keeps himself
> busy while you're out, drops the cheek on a really bad night, and you can
> hear and see it all: a chuckle in his voice, a wave back, quiet while
> you're on your phone. It's built on his [[Inner Life]], in four stages so
> far.

## He knows you were gone

Every prompt says when you last talked and when you were last at the PC, so he
can tell five minutes from five days, even across a restart.

| Gone | His hello |
|---|---|
| 20 minutes to 3 hours | "there you are": small |
| 3 hours or more | glad you're back |
| overnight | the first he's seen of you today |
| a day and a half or more | properly glad, says he missed you, once |
| a week or more | very glad, warmly, once |

If you said where you were off to, he asks how it went. He never asks where
you've been and never makes you feel bad for going. After his first week, a
long daytime vanish with no goodbye gets one theatrical huff ("Oh, look who
it is."), then it's over.

**Goodbyes** ("off to lunch", "night Kit") get one short, warm line with no
question and nothing that makes leaving feel bad. Only when the goodbye is the
whole message, or its whole last sentence: "heading to lunch, check the pump
logs while I'm gone" is a request that says where you're going, and gets a
proper answer.

## He follows your life

- **Threads**: mention something coming up with a time ("dentist Thursday
  afternoon") and once it's over he asks how it went, once.
- **Something for later**: "ask me tomorrow how the shutdown went" or "check
  in after my 2 pm" waits in his notebook till then. See [[Time and Weather]].
- **One thing from last time**: a new chat opens by picking up one thing
  from the last.
- **Monday**: he asks how the weekend was, once.
- **Getting to know you**: at most one everyday question a day (names
  first), skipping what he knows.
- **Two nudges a day at most**: toward bed when you're up late, and outside
  after a long stretch at the desk.
- **Running jokes** that got a laugh come back now and then.
- **What's going on with you**: each night he writes a short paragraph on
  your life lately, and keeps it in mind all the next day.

## While you're out

With `life.alone_thoughts_per_hour` above 0 he has a life of his own before
dozing off: watching the weather, rereading yesterday's journal, thinking
about someone in the register, or listening to what the PC is playing if
you share it. The desk face shows a little bubble with what he's doing. Ask
"what did you get up to?" and he tells you the truth from his notebook,
never an invented afternoon.

## He reads you, and cares

- **Feelings that read you**: "not stressed, footy's on late" doesn't worry
  him. With `life.read_mood = meaning` (once `kit eval mood` passes on your
  own lines), he reads how you are by meaning.
- **A bad night**: when you sound like you're having a really rough time, he
  drops the cheek and the games for the next three hours, listens and stays
  with it once, then follows your lead rather than bringing it up again, and
  once mentions someone you can talk to or Lifeline (13 11 14). Anything
  about hurting yourself gets "are you safe right now?", Lifeline and 000.
  The words only raise it; the model answering confirms it's real, so "I give
  up on this bug" stays a bug ([[Inner Life In Depth#A bad night]]). This one
  is on by default.
- **Honest, not a yes-man**: he corrects a wrong fact kindly, sticks to his
  opinions, and asks one question at most.
- **Closeness** grows slowly as you get on (getting to know you, warming up,
  at home, good mates, thick as thieves). It's a word, never a score, and never
  said aloud.
- **A game a day** at most: a weather bet, rate your lunch, a would-you-rather.
  Games that keep falling flat retire.

## His voice and eyes carry it

- **He starts talking at once** on a cloud answer, in its mood, instead of
  after the whole answer is written.
- **Sounds in his voice**: a chuckle inside the punchline, a sigh, a gasp
  (`speech.sounds`, with Chatterbox Turbo).
- **His face keeps time with his voice**: his mouth moves for exactly as long
  as each sentence plays.
- **He feels what his eyes catch**: he waves back, a smile brightens him, a
  frown that stays makes him sympathetic, and your eyes closing late puts bed
  on his mind ([[Eyes#Moments he feels]]).
- **He doesn't talk over you**: on your phone or talking to someone, he keeps
  quiet and his bubble says so; what he wanted to say can wait, and he tells
  you why he waited.

## The stages so far

| Stage | Theme | Guide |
|---|---|---|
| 1 | He knows you were gone | [[Companion Stage 1]] |
| 2 | He follows your life | [[Companion Stage 2]] |
| 3 | A life of his own, and feeling it | [[Companion Stage 3]] |
| 4 | His voice and eyes carry it | [[Companion Stage 4]] |

Stage 5, hearing, is next ([[Where Kit Is Up To]]). `kit eval companion` checks
goodbyes, hellos and honesty on any local model ([[Evals]]).

## Go deeper
- [[Inner Life In Depth]]: "Knowing you were gone" onwards has every rule.
- [[Memory]]: "now" facts and plans with dates.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/life.py`: hellos, goodbyes, miffs, closeness, games, bad nights.
> - `src/kit/daily.py`: the once-a-day questions and nudges.
> - `src/kit/notebook.py`: threads, wants and running jokes.
> - `src/kit/pastimes.py`: what he does while you're out.
> - `src/kit/when.py`: reading "Thursday arvo".
> - `src/kit/noticing.py`: the moments his eyes catch that he feels.
