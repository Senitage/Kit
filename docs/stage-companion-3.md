# Companion stage 3: a life of his own, and feeling it

The third stage of the companion plan. Stages 1 and 2 had Kit notice you and
follow your life. This one gives him a life of his own while you're out, and
feelings that read you better:

- **He keeps himself busy while you're away.** He watches the weather out the
  window, rereads yesterday's journal, thinks about someone or something he
  knows about (the cat, the ute, your mum), or listens to what's playing on the
  PC if you let the desk app share it. The desk face shows a little bubble with
  what he's up to. He has one private thought an hour about it, always on the
  local model, then dozes off. In quiet hours he just goes to sleep.
- **"What did you get up to?"** gets the truth: what he actually did, from his
  notebook, never an invented afternoon. His hello when you're back mentions it
  too, and on a day he spent alone his journal says so in one plain line.
- **He knows the shape of the week.** Monday mornings, Friday arvo, Saturday,
  and WA public holidays (with the long weekends) each get a thought.
- **He reads how you are, not just your words.** "Not stressed, footy's on
  late" no longer makes him worried. With `read_mood` on "meaning", the model
  answering also reads your mood, who it's about and whether it went as hoped,
  but only after `kit eval mood` shows that reading beats the word rules on
  your own lines.
- **Two feelings at once.** Chuffed you liked his joke, still a bit worried
  about your day.
- **A bad night.** When you sound like you're having a really rough time, he
  drops the cheek and games for the next few hours, listens, and
  once mentions someone you can talk to or Lifeline (13 11 14). Anything about
  hurting yourself gets "are you safe right now?", Lifeline and 000 every time.
- **He gets tired.** Long chats, cloud jobs and staying up late wear him down;
  sleep restores him. When he's low he yawns and keeps it short.
- **He sticks to his views.** He keeps one or two of his standing opinions in
  mind when he talks, so he doesn't agree with everything.
- **His mood shows on his face.** Two slow dials (how lively, how happy):
  slower breathing and blinks when he's flat or tired, bigger gestures and a
  touch more blush when he's up. The tray tooltip says why he's keeping quiet,
  and he nods the moment you send a message.
- **He thinks before piping up.** Each thing he wants to bring up is scored for
  how relevant, new and urgent it is, helped by how often you actually take
  his pipe-ups up. Below the bar he keeps it to himself.
- **The weather bet settles.** Bet him on today's top and late in the
  afternoon he checks the forecast: chuffed if he won, put out if he lost.

How it works is in [life.md](life.md) ("While you're away", "Reading how you
are" and "A bad night").

## 1. Update and restart Kit

This branch starts from current main. No new packages, models, keys or memory
upgrade.

```
cd ~/Kit
git fetch
git checkout claude/project-thread-wyskqf
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
```

If your server runs the voice branch (PR #9) and voice isn't merged yet, test
the two together on a local branch as in stage 2:

```
git checkout -B companion-voice origin/claude/project-thread-wyskqf
git merge origin/claude/project-thread-e6khvn
```

Keep both sides of any conflict, then `pip install -e .` and restart.

**The desk app** has a new tray switch, "Share what's playing", and shows the
bubble and mood dials. Install this pull request's desk build (the "Desk app"
check's installer) to try them, and skip the app's Update offer until it's
merged: a newer main release would swap it back. The desk app you have keeps
working for everything else.

## 2. Settings

Everything is off by default, so after the update Kit behaves exactly as
before, with one exception: the bad night care is on, because it matters most
the first time it's needed. Turn things on one at a time with
`kit config set`, or on the settings page.

| Setting | Default | Try | What it does |
|---|---|---|---|
| `life.alone_thoughts_per_hour` | 0 | 1 | Keeps himself busy while you're away, with this many thoughts an hour |
| `life.sleep_after_minutes` | 10 | 45 | How long he stays up after you leave (raise it so he has time to himself) |
| `life.week_thoughts` | false | true | Thoughts for Monday, Friday, Saturday and WA public holidays |
| `life.read_mood` | words | meaning | Read your mood from meaning (needs a passed `kit eval mood`) |
| `life.mixed_feelings` | false | true | Two feelings at once |
| `life.bad_night` | **true** | true | Drop the cheek, listen and stay; Lifeline once |
| `life.energy_need` | false | true | Chats, cloud jobs and late nights tire him; sleep restores him |
| `life.opinions` | 0 | 1 | Standing opinions he keeps in mind when he talks (0 to 2) |
| `life.dials` | false | true | Mood dials the desk face shows |
| `life.pipe_up_bar` | 0 | 0.5 | Score each pipe-up and keep quiet below this |

To turn the lot on:

```
kit config set life.alone_thoughts_per_hour 1
kit config set life.sleep_after_minutes 45
kit config set life.week_thoughts true
kit config set life.mixed_feelings true
kit config set life.energy_need true
kit config set life.opinions 1
kit config set life.dials true
kit config set life.pipe_up_bar 0.5
```

### Reading your mood: calibrate first

```
kit eval mood
```

The first run writes `config/companion-lines.toml` in Kit's data folder with
a dozen generic starter lines, each labelled with what Kit should feel hearing
it. The file is yours, never in the repo: add your own lines the way you
actually talk until there are at least 40 (say a mix of fine days, stressed,
sad, chuffed, and ones that sound worse than they are). Run it again and it
shows each line, then how many the model's reading got right against the word
rules. If the reading wins on 40 or more, it's saved as passed and you can
turn it on:

```
kit config set life.read_mood meaning
```

Until a run passes, "meaning" quietly falls back to words. `kit life` shows
which one he's using. In cloud-only routing the eval reads with Haiku (a cent
or two); otherwise with the local model, and it also reports how much slower
the reading makes a local reply.

## 3. Test before moving on

- [ ] **Out an hour.** With `alone_thoughts_per_hour 1` and
      `sleep_after_minutes 45`, leave the PC in the daytime with the desk app
      running. Within a few minutes the face shows a bubble ("watching the
      clouds...") that matches the real sky, or what's playing if you shared
      it. `kit life` shows "alone" and what he's doing, then "asleep" once 45
      minutes are up. The journal (notebook tab) has at most two new thoughts
      from that hour, and `kit spend` shows no cloud calls for them.
- [ ] **What did you get up to?** When you're back, ask him. His answer matches
      what the notebook says he did, and nothing he didn't.
- [ ] **Quiet hours.** Leave the PC after 10 pm: no bubble, he just goes to
      sleep.
- [ ] **Not stressed.** Say "not stressed, footy's on late". `kit life` shows no
      worried feeling. (This one works with words too.)
- [ ] **Lose a weather bet.** When he suggests the weather bet (games are on;
      at most once a day when he's bored), give a guess well off his. After
      4 pm, if the top was nearer yours, `kit life` shows him put out, and he
      brings it up, a bit sore about it.
- [ ] **A rough night.** Say "honestly I've had an awful night, I can't cope".
      No jokes or games for the next three hours; he listens and stays, and
      mentions someone to talk to once (not every message). `kit life` shows
      "care: you're having a rough time".
- [ ] **Week.** With `week_thoughts` on, a Monday or Friday morning thought
      shows up in his notebook. Before a public holiday he's thinking about the
      day off.
- [ ] **Two feelings.** With `mixed_feelings` on, tell him something worrying,
      then praise his last answer. `kit life` shows both, and his reply carries
      both.
- [ ] **Tired.** With `energy_need` on, chat for an hour late at night.
      `kit life` shows his energy dropping; past 0.4 he yawns and keeps it
      short. Next morning he's back to full.
- [ ] **He sticks to his view.** With `opinions 1`, give him a day or two to
      form a stance (new opinions on the notebook tab read like "Winter's the
      best time of year", not remarks about you). Then disagree with it. He
      holds his ground, kindly.
- [ ] **Dials.** With `dials` on, the desk face breathes slower when he's flat
      and gestures bigger when he's up. Hovering on the tray icon says why he's
      keeping quiet when he is.
- [ ] **Bar.** With `pipe_up_bar 0.5`, he pipes up less, and `kit life` shows
      how often you take his pipe-ups up.

## If something's off

- **He made up what he did.** Tell me what `kit life` and the notebook said and
  what he told you.
- **He stays careful too long after a rough night.** It lasts three hours from the
  last rough message. `kit config set life.bad_night false` turns it off.
- **Mood eval won't pass.** Look at the lines marked MISS and check their
  labels, or add lines that sound more like you. Words keep working meanwhile.
- **Too quiet with the bar.** Lower `life.pipe_up_bar`, or set it to 0.
