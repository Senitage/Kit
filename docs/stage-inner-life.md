# Side stage: Kit's inner life

Kit now has a life between conversations, so he feels like someone rather than
something that waits to be spoken to:

- **Feelings with a reason.** Call him a legend and he's chuffed for an hour or
  so; say you're stressed and he's a bit worried about you. He knows why he
  feels what he feels, and it shows in what he says and how he fidgets.
- **Thoughts of his own.** Every few minutes while you're at the PC, and sooner
  when something happens, he has a private thought. "What are you thinking
  about?" gets the real one.
- **Things he wants to bring up.** A thought can become something he wants to
  ask you. It presses harder the longer it waits, and his next pipe-up brings it
  up. "Ask me tomorrow how the shutdown went" waits till the morning.
- **A notebook.** His thoughts, opinions, wants, moments, a daily journal, and
  a self-sheet: who he thinks he is, in his own words. It's on the memory page,
  where you can forget any of it.
- **Each night, a look back.** He writes his journal and updates his self-sheet
  and quirks, so he grows a little each day around the persona you gave him.
- **Each week, a review.** A stronger model checks how he's changed. You can
  undo any change, and he's told what you undid.
- **Two passes when he talks.** The local model decides what to do, then says
  his words in plain text, which sounds more like him. `kit eval voice` compares
  local models on how alive they sound.
- **A restart doesn't wipe him.** How he feels and why, his drives, whether he's
  sulking and how long since you talked survive a restart.

How it all works is in [life.md](life.md). Finish [stage 2](stage-2-desk-app.md)
first: Kit needs the desk app to know you're at the PC before he'll think.

## 1. Update and restart Kit

In the Ubuntu terminal:

```
cd ~/Kit
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
```

There are no new packages, models or keys, and memory needs no upgrade. Soon
after it starts, Kit writes his first self-sheet from the persona, using the
work model (about a cent). `kit life notebook` shows it.

## 2. What it costs

| What | Who does it | Roughly |
|---|---|---|
| Thoughts (up to 6 an hour) | the local model | free |
| Nightly reflection | the work model (Sonnet) | 2 cents a day |
| Weekly review | the expert model (Opus) | 3 to 5 cents a week |

The reflection and review are logged as spend with the rest, under "Kit's
reflection on ..." and "Kit's weekly review" (`kit memory spend`), and count
toward the monthly cap. For no cloud at all, `kit config set life.reflect_with
local` has the local model write his diary (flatter, but free), and `off` stops
him reflecting and changing.

## 3. Pick his voice: the local model bake-off

The local model gives Kit his voice. `kit eval voice` puts the same 16 things to
each model you name (greetings, "how are you feeling?", "the build failed
again", "you're just a robot"...), plus four pipe-ups and two private thoughts,
with a made-up afternoon on the PC and a few notebook entries so there's
something to be alive about. It runs on a scratch memory (Kit's real memory and
notebook aren't touched), uses only local models, and costs nothing.

Pull the candidates (a few GB each):

```
ollama pull gemma4:e4b
ollama pull qwen3.5:9b
ollama pull ministral-3:8b
```

Then run the bake-off. Each model takes a few minutes:

```
kit eval voice --models qwen3:8b gemma4:e4b qwen3.5:9b ministral-3:8b
```

It prints one line per model, like this made-up one, and writes every reply
side by side to a Markdown file in the data folder (the path is printed at the
end):

```
qwen3:8b (two passes): 20/20 answered, first words 0.9s (median), 2 echoes, 1 canned, variety 81%, 14 words a line, 2/2 thoughts
```

- **answered**: replies that came back at all, out of the 16 prompts and 4
  pipe-ups. Anything short of all of them is a problem.
- **first words**: how long before he starts talking. Under about 1.5 s feels
  live.
- **echoes**: lines that copy one of his example lines, a built-in voice line,
  or something he already said in the run. Should be 0.
- **canned**: assistant-speak ("as an AI", "how can I help", "great
  question"). Should be 0.
- **variety**: how much of the wording is new rather than reused. Higher is
  better.
- **thoughts**: private thoughts he actually had. Nothing coming to mind now
  and then is fine.

The numbers rule out bad models; reading the file picks the winner. Read the
same prompt across models and choose the one that sounds most like a small
cheeky creature on your desk, not a help desk. Then:

```
kit config set ollama.model gemma4:e4b
```

Two more runs worth doing:

- `kit eval voice --one-pass` compares the old single JSON pass. Two passes
  should read livelier; if they don't for your model,
  `kit config set ollama.speak_pass false` saves the half second.
- Cheek: `kit config set life.cheek 0.2`, run `kit eval voice`, then
  `kit config set life.cheek 0.9` and run it again. The two files should read
  like different moods of the same Kit. Set it back where you like it (0.6 by
  default).

## 4. Test before moving on

Use him normally for a few days with the desk app running. Then:

- [ ] **He's thinking.** With you at the PC, `kit life` shows a `thinking:` line
      in his own words. Over an hour of normal work it changes, and it's about
      what you're actually doing.
- [ ] **Real thoughts, not inventions.** Ask "What are you thinking about?". He
      gives that thought (or one of his last few), not a new one made up on the
      spot.
- [ ] **Something new on screen.** Open a site he hasn't seen today. Within 10
      minutes, a thought on the notebook tab (or `kit life notebook`) mentions
      it, and his next pipe-up is about it or something he meant to ask.
      `kit life poke` makes him pipe up now if you don't want to wait.
- [ ] **Something for tomorrow.** Say "Ask me tomorrow how the shutdown went."
      `kit life` lists it under `later:`. Next morning he asks you, unprompted,
      and only once.
- [ ] **A sulk survives a restart.** Leave a pipe-up unanswered for 10 minutes
      (he sighs), then `sudo systemctl restart kit`. `kit life` still shows him
      sulky and put out, with why, and "what's up?" gets the reason.
- [ ] **Quirks change, and you're told.** For three days, laugh at one of his
      quirks whenever it shows ("haha", "love it") and ignore another (quirks
      are in `kit life`). After the next weekly review, the first is a running
      joke in his self-sheet and the second is gone, and the review on the
      notebook tab told you about it. "Give back" or "Go back to this" undoes it,
      and he doesn't redo it.
- [ ] **The notebook.** The memory page has a Kit's notebook tab with his
      self-sheet, quirks, wants, thoughts, opinions, moments and journal.
      Forget an entry and it's gone from the tab and from what he recalls.
- [ ] **His voice.** In `kit eval voice`, cheek 0.2 and 0.9 read differently,
      and nothing copies a voice line or a recent reply (0 echoes).
- [ ] **Cheap.** `kit memory spend` shows each night's reflection under 10 cents.

`kit life think` (a thought now) and `kit life reflect` (look back on today so
far, a few cents) help when you don't want to wait. Tonight's reflection
replaces a journal entry written early by `kit life reflect`.

## If something's off

- **No thoughts.** `kit life` says when the next one is due. He only thinks
  while the desk app says you're at the PC (or within half an hour of a chat),
  never mid-conversation or asleep, and not when `life.thoughts_per_hour` is 0.
  `kit life think` shows what the local model makes of it; "Nothing came to
  mind" every time means it isn't answering.
- **No reflection.** It runs within an hour after midnight while the brain is
  up, so a PC that sleeps at night reflects when it wakes. `logs/kit.log` has a
  warning for each try that failed, and says when he gave up on a day (after
  three tries).
- **He's drifting.** Go back to an earlier self-sheet on the notebook tab, or
  change the persona: when its traits change, his prompt shows them beside his
  self-sheet until his next reflection folds them in.
- **Too chatty or too quiet.** `life.chattiness`, `life.max_per_hour` and
  `life.thoughts_per_hour`; see [life.md](life.md).
- **He repeats himself.** A pipe-up that would only repeat something he said
  lately gets three goes, then he keeps quiet (`kit life` says "had nothing new
  to say"). If that happens often, the model is the weak spot: compare others
  with `kit eval voice`, where a dropped pipe-up shows as "kept quiet".
- **A grey box under his words.** That's something to read that he didn't say
  aloud: code, steps, a list, a link or a path. Nothing else goes there.
- **A grey line like `curious · tilt_head` under his words.** That's how he
  felt and the gesture he made.
