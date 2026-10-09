# Companion stage 2: he follows your life

The second stage of the companion plan. Stage 1 taught Kit that you come and
go; this one has him keep up with your life between chats, the way a mate
does:

- **He asks how it went.** Say "got the dentist Thursday arvo" and on Thursday
  evening he asks how the dentist went, once. "Check in after my 2 pm" gets a
  check-in about 2:30. He understands times the way you say them: "this arvo",
  "tonight", "Thursday week", "after work", "at 5".
- **He doesn't ask what he already knows.** Tell him "dentist was fine" first
  and he won't ask. Each night he writes a short paragraph on what's going on
  with you lately, and it's in front of him all the next day.
- **A new chat picks up one thing from the last**, and on Monday morning he
  asks about the weekend, once.
- **He gets to know you.** While you're chatting, at most once a day, one
  everyday question: your partner's name, the cat's, your family, your mates,
  footy, music. He skips what he knows.
- **Two nudges, once a day each:** toward bed when you're up past 10:30 pm, and
  outside after three hours at the desk without a break.
- **Running jokes.** A joke that got a laugh comes back now and then, when you
  say something that sets it off, and is dropped if it keeps falling flat.
- **He remembers what matters.** "Now" facts ("I've been sleeping badly") last
  two weeks. Plans keep their date. People and things about you count for more
  in recall. "Emma's my cousin" puts right "Emma, Dan's sister".
- **Claude for the moments that matter.** Opus writes his nightly reflection.
  Sonnet answers when you've had bad news, and says hello after a night or
  days away. As the budget runs low, evals stop first and the nightly
  reflection keeps the last few dollars.
- **Code and builds on your screen don't set him off** any more.

How it all works is in [life.md](life.md) ("Something for later" and
"Following your life") and [memory.md](memory.md) ("What matters, and what's
only lately").

## 1. Update and restart Kit

This branch starts from main with stage 1 merged. No new packages, models,
keys or memory upgrade: everything new is kept beside what's already there.

```
cd ~/Kit
git fetch
git checkout claude/project-thread-wyskqf
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
```

If your server is on the voice branch (PR #9) and voice isn't merged yet, this
branch alone won't start: your settings have voice keys it doesn't know. Test
the two together on a local branch:

```
cd ~/Kit
git fetch
git checkout -B companion-voice origin/claude/project-thread-wyskqf
git merge origin/claude/project-thread-e6khvn
```

Until the voice branch has stage 1 merged in, that merge stops on conflicts in
the brain, server, settings and README: keep both sides of each. Then
`pip install -e .` and restart as above.

The desk app you have keeps working; there's no new desk build.

## 2. Settings

All on by default except work triggers. Change any with `kit config set`, or
on the settings page.

| Setting | Default | What it does |
|---|---|---|
| `life.threads` | true | Follow things coming up and ask how they went |
| `life.chat_opener` | true | A new chat (and the hello) picks up one thing from the last |
| `life.interview` | true | One getting-to-know-you question a day, while chatting |
| `life.nudges` | true | The bed and outside nudges |
| `life.bedtime` | 22:30 | When the bed nudge starts |
| `life.desk_hours` | 3 | Hours at the desk before the outside nudge |
| `life.work_triggers` | false | Code and builds on screen make him curious or sympathetic |
| `life.reflect_role` | expert | Who writes the nightly reflection: `expert` (Opus) or `work` (Sonnet) |
| `routing.key_moments` | true | Sonnet answers bad news and long-absence hellos |
| `routing.key_moment_strength` | 0.7 | How hard news must hit to count |
| `cloud.reserve_usd` | 3 | Each step of the budget order keeps this much more |
| `memory.now_days` | 14 | How long a "now" fact lasts |
| `memory.weight_floor` | 0.3 | 1 turns off weighing recall by importance and recency |

Opus for the nightly reflection costs a few cents a night instead of about 2 cents.
`kit config set life.reflect_role work` goes back to Sonnet.

## 3. Test before moving on

Use him normally for a few days with the desk app running. Then:

- [ ] **Thursday arvo, asked Thursday evening only.** On a Tuesday say "got the
      dentist Thursday arvo". The notebook tab's "Things he'll ask about" shows
      "dentist, Thursday afternoon". He doesn't mention it Wednesday. Thursday
      from about 5 pm, at his first chance (a pipe-up, or your first message),
      he asks how it went, once. Answer, and the notebook shows what you said.
- [ ] **Check in after my 2 pm.** Before 2 say "check in after my 2 pm". `kit
      life` shows it under "later". About 2:30, if you're at the PC, he checks
      in, or when you're back if you're away.
- [ ] **Emma's my cousin.** If Kit has a fact calling someone your sister (add
      one on the memory page if not: "Emma, Dan's sister, celebrates her
      birthday on the 14th of March"), say "Emma's my cousin". The memory page
      shows the fact with cousin and the birthday kept, and History shows the
      old one.
- [ ] **Monday morning, the weekend once.** On Monday morning, at the PC, he
      asks how the weekend was, once. If you'd told him about something on the
      weekend ("footy Saturday"), he asks about that instead.
- [ ] **A new chat opens with one thing from the last.** Chat about something
      in the evening ("been sorting the shed, it's a mess"). Next morning your
      first message gets an answer that picks one thing up ("did the shed win?"),
      with one question at most. A second message a few minutes later doesn't.
- [ ] **He knew already.** Say "dentist this arvo", then after it "dentist was
      fine". He doesn't ask how it went later.
- [ ] **What's going on with you.** The morning after a day of chatting, the
      notebook tab's "What's going on with you" has a short paragraph. Ask
      something it covers ("what's Sarah up to?") and he answers from it.
- [ ] **A getting-to-know-you question.** Within a day or two of chatting he
      asks one everyday question. Answer a name question with just the name
      ("Milo") and the memory page has "Milo is Dan's cat." He doesn't ask it
      again.
- [ ] **Bed.** Chat after 10:30 pm. One light nudge toward bed, once a night.
- [ ] **Outside.** Three hours at the desk without a 5-minute break in the
      daytime gets one nudge to get some air or see someone.
- [ ] **Bad news.** Say "my dog died this morning" (or something like it).
      The answer comes from Sonnet (`kit spend` lists the call), kind and
      short. "Keep it local: ..." with the same news is
      answered at home.
- [ ] **Kept local stays local.** Say "keep it local: the doctor wants more
      tests", then "ask Claude what I just told you". Claude (`kit spend`
      lists the call) doesn't know about the doctor. Anything Kit learns from
      it shows "kept off the cloud" on the memory page.
- [ ] **Nothing about your code.** Open VS Code for an hour. He doesn't pipe up
      about the files, and a failed build on screen doesn't make him
      sympathetic.

- [ ] **The eval.** `kit eval companion --models gemma4:e4b` now also checks
      that a new chat picks up the footy final from a few hours before, and that
      a pipe-up asks about the dentist once it's over. It runs on the local model
      only, with key moments off.

## If something's off

- **He asked about something before it happened.** Check the thread's "asks
  from" time on the notebook tab. If the time was misread, forget the thread
  and tell me the words you used.
- **He started a thread that isn't one.** Forget it on the notebook tab. If it
  keeps happening, `kit config set life.threads false` and tell me the words.
- **No opener.** A new chat starts after `brain.new_chat_after_minutes` (2
  hours) quiet. With the desk app reporting, the hello when you sit down picks
  the thing up instead. Short messages ("ok", "thanks") aren't picked up.
- **Too many questions.** `kit config set life.interview false` stops the
  getting-to-know-you ones; `life.nudges false` stops the nudges.
- **Key moments too often, or not at all.** Raise or lower
  `routing.key_moment_strength`, or turn them off with
  `routing.key_moments false`.
