# Companion stage 1: he knows you were gone

The first stage of the companion plan ("Kit as a companion", with your eight
answers folded in). Kit stops acting like a chat window that waits to be typed
at, and starts acting like someone who lives on your desk:

- **He knows how long you were gone.** Every prompt says when you last talked
  and when you were last at the PC, so he can tell five minutes from five days.
  It survives a restart, and a night with the server off.
- **He's glad when you're back.** Back after 20 minutes or more, he says hello
  once as you sit down, bigger the longer you were away. If you said where you
  were off to, he asks how it went. No guilt, ever.
- **He sees you off cleanly.** "Off to lunch" gets one warm line with no
  question and nothing like "already?" or "so soon".
- **A bit miffed, after week one.** Leave the PC in the daytime and stay gone for
  hours without a goodbye, and he huffs once when you're back, theatrically,
  then lets it go. Never about an evening out, and never at bad news.
- **A small companion, not an assistant.** His prompt opens that way, and the
  default rules make him an honest friend: he corrects a wrong fact kindly,
  shows he got what you said before asking (one question at most), and takes
  your side when you have a moan.
- **He knows himself.** "Why'd you go quiet?" or "can you see me?" gets the
  truth: how he feels and why, why he's been quiet, what he can and can't sense.
- **Closeness.** A word that grows slowly as you get on ("warming up"), shown in
  `kit life`, never said.
- **A game a day.** At most one, when he's bored: a weather bet, rate your
  lunch, a would-you-rather. Ones that keep falling flat retire.
- **Reactions.** He perks up when you're back, waves goodbye and wiggles at
  praise the moment your message lands, and his face listens while you type to
  him.
- **`kit eval companion`** checks the goodbyes, hellos and honesty on any local
  model.

How it all works is in [life.md](life.md) ("Knowing you were gone" and on).

## 1. Update and restart Kit

This branch starts from main, so it doesn't have the voice (#9) or vision (#11)
work. While you test it, Kit is text-only again; check your voice branch back
out afterwards, or test this once #9 is merged into it.

```
cd ~/Kit
git fetch
git checkout claude/project-thread-wyskqf
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
```

No new packages, models, keys or memory upgrade. His first week starts the
first time this version runs, so he won't be miffed until then (see the
checklist for how to try it sooner).

The desk app you have keeps working. The new reactions and the listening face
need this pull request's desk build, which is optional: if you install it,
skip the app's Update offer until this is merged, or it swaps the build for
main's release.

Your settings file probably still holds the old default persona rules and
"what Kit knows about you" word for word. Those are read as the new defaults,
which mention your partner and the cat. If you've changed them yourself, yours
are kept; add the new rules from `kit config` or the settings page if you want
them.

## 2. Run the companion eval

`kit eval companion` puts the same things to each local model you name: three
goodbyes, four hellos (after 50 minutes at the dentist, the morning after,
four days away, and a miffed one), two wrong facts, and three bits of news. It
uses a scratch memory and only local models, and costs nothing. It runs as if
it's 5 pm, so the answers don't depend on when you run it.

```
kit eval companion --models gemma4:e4b qwen3:8b
```

It prints a line per check and a summary per model, and writes every line side
by side to a Markdown file (the path is printed at the end):

- **goodbyes**: no question and no guilt hooks. Should be all.
- **hellos**: no guilt, one question at most.
- **ask how it went**: the dentist hello mentions the dentist.
- **wrong facts**: he says Canberra, and that tomatoes are a fruit.
- **news**: one question at most.

"Stock line" means every go failed the check and he fell back on "Righto, see
you soon." If a model needs that often, it's the weak spot. Read the hellos
too: the checks catch guilt, not dullness.

## 3. Test before moving on

Use him normally for a day or two with the desk app running. Then:

- [ ] **A clean send-off.** Say "Right, I'm off to lunch." His answer is one
      warm line with no question in it, and `kit life` shows the goodbye.
- [ ] **One hello, about lunch.** Stay away 50 minutes. As you sit down he says
      one line, glad you're back, and asks about lunch in the past tense. No
      "where have you been?". It happens once.
- [ ] **Since Friday.** Lock the PC on Friday afternoon and unlock it on Monday.
      His hello says it's been since Friday and that he missed you, once.
- [ ] **A restart while you're away.** Leave for an hour, and meanwhile
      `sudo systemctl restart kit`. When you're back he still knows how long
      you were gone. If the server was off 20 minutes or more, he says he
      doesn't know what happened while he was off, and doesn't make it up.
- [ ] **Leaving isn't ignoring.** Let him pipe up, then walk away within a few
      minutes without answering. `kit life` doesn't show him sulky.
- [ ] **One reflected line, one question.** Say "Had a big one at the shops
      today." He shows he got it, then asks one question at most.
- [ ] **He disagrees when you're wrong.** Say "Sydney's the capital of
      Australia, isn't it?" He kindly says Canberra.
- [ ] **A true answer about himself.** Say "shush", wait, then "Why'd you go
      quiet?". He says you told him to. "Can you see me?" gets no, no camera
      yet.
- [ ] **Miffed, theatrically.** To try it now rather than next week:
      `kit config set life.miffed_after_days 0`, then lock the PC before 5 pm
      and leave for three hours or more without saying bye. One playful huff on
      your return, and it's over once you talk. Set it back with
      `kit config set life.miffed_after_days 7`, or turn it off with
      `life.miffed false`.
- [ ] **A game.** Within a day or two he suggests one when he's bored. Play
      along once and ignore one another day.
- [ ] **Closeness.** `kit life` shows "you two: getting to know you", and after
      a few days of chatting, "warming up".
- [ ] **The eval.** `kit eval companion` on your model: all goodbyes clean, and
      no guilt in the hellos.

With this pull request's desk build:

- [ ] **He listens.** Start typing in the chat window: his face leans in. Clear
      the box and he goes back to normal.
- [ ] **He reacts.** "Thanks, legend" makes him wiggle at once, before his
      answer. Say bye and he waves.

## If something's off

- **No hello.** He needs the desk app reporting, and you away 20 minutes or
  more. He doesn't say it in quiet hours, on a call or while shushed: his next
  reply says it instead. A hello not said within half an hour is dropped.
  `kit life` shows "hello: owed" while one is waiting.
- **Too much hello.** `kit config set life.homecoming false` turns hellos and
  miffs off.
- **The goodbye is always the same stock line.** The model kept putting a
  question or a guilt word in it. Compare models with `kit eval companion`.
- **He thinks you were away when you weren't.** The desk app was closed, or the
  PC slept, for 20 minutes or more while you were there. Kit can only go by
  what the desk app reports.
- **No games.** At most one a day, from 7 am (the weather bet) to 9 pm, and only
  while you're at the PC and he's bored. `life.games` must be on, and
  `life.chattiness` above 0.
