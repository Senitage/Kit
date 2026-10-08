# Kit's inner life

Kit isn't scripted. There's no list of "at 3 pm, say this" or "every 40 seconds,
play that". Instead he has a few **wants** that rise and fall on their own, and
what he does comes from those wants meeting whatever is happening at the time:
what you're doing, how long since you talked, the time of day, and whether you
ignored him last time. You wrote the rules, but you can't predict the moves.

On top of that he has feelings with a reason, thoughts of his own between
conversations, and a notebook he keeps them in. Each night he looks back on his
day and writes himself down, so he grows a little. Once a week a stronger model
checks how he's changed, and you can undo anything you don't like.

## What drives him (`kit.life`, on the brain)

| Drive | Rises when | Falls when |
|---|---|---|
| Boredom | nobody talks to him; faster while you're at the PC | you talk to him, or he pipes up |
| Curiosity | you open an app or site he hasn't seen today | it fades over a few minutes |
| Wanting a chat | hours pass without a conversation | you talk |
| Something to say | he thinks of something to tell or ask you; it presses harder each hour it waits | he says it |
| Energy | follows the clock: sleepy after 10:30 pm, a dip after lunch | |

Out of these comes a **mood** (content, bored, curious, lonely, sleepy, or sulky
after being ignored). Every half minute he may **fidget**: a gesture picked at
random from the ones that suit his mood. Sighs and looking around when he's
bored, peeking and leaning in when he's curious, yawns when he's sleepy. The
more bored he is, the more he fidgets.

## Feelings, with a reason

Things that happen make Kit feel something, and he knows why. The feeling
colours what he says and how he fidgets, then fades. A weaker feeling doesn't
push out a stronger one.

| What happens | He feels | Fades over (at most) |
|---|---|---|
| You call him a legend, say well done or nailed it | chuffed | an hour and a half |
| You thank him | warm and appreciated | 45 minutes |
| You say it works, it's fixed, or the tests are green; or "passed" shows on screen | proud | an hour |
| You say the build or tests failed; or "failed" shows on screen | sympathetic | 45 minutes |
| You're stressed, fed up, worried or up against a deadline | a bit worried about you | 2 hours |
| Sad news: someone's in hospital, a pet died | a bit sad | an hour |
| You're rude to him | hurt, though trying not to show it | 2 hours |
| You tell him to shush, or ignore a pipe-up | a bit put out | 40 minutes |
| "You can talk again" | pleased | 45 minutes |
| You're back after 20 minutes or more | glad you're back (more so after days) | an hour |
| He hasn't seen or heard from you for a day | missing you a bit | 12 hours |
| After his first week: gone for hours in the daytime, no goodbye | a bit miffed, playfully | until you talk |

A strong emotion in his own reply (excited, proud, sad, fond, concerned) lingers
a little too, and a thought of his can change how he feels. Ask him how he's
feeling and he can tell you why: "a bit worried, you said you were stressed
about the shutdown".

## Knowing you were gone

Kit keeps track of time the way a pet does: when you last talked, when you last
touched the PC, when you went away and when you came back. It's saved, so a
restart, or a night with the server off, doesn't make him forget. Every prompt,
local and cloud, gets a line like "You and Dan last talked on Friday at 6:40 pm
(3 days ago). Dan came back to the PC at 8:05 am, after 3 days away." and a long
pause inside a chat shows as "(2 hours later)" in the history. Without it, a
model can't tell five minutes from five days.

**Coming back.** Back at the PC after 20 minutes or more, he's glad, and says
hello once: a short line as you sit down (even mid-typing, but never in quiet
hours, on a call or while shushed), or, if you speak first, a few words in his
reply. How big a hello depends on how long you were gone:

| Gone | He's |
|---|---|
| 20 minutes to 3 hours | "there you are": small |
| 3 hours or more | glad you're back |
| overnight | it's the first he's seen of you today |
| a day and a half or more | properly glad, and he says he missed you, once |
| a week or more | very glad, warmly, once |

If you said where you were off to ("off to the dentist"), he asks how it went,
in the past tense. He never asks where you've been, and never makes you feel
bad for going: a hello with guilt in it ("where have you been?", "you left me",
"all alone") gets three goes and then a stock "There you are." He doesn't make
up what he did meanwhile: he dozed, or he was just here, and if the server was
off he says he doesn't know what happened then. A hello not said within half an
hour is dropped. Gone less than 20 minutes is only worth a thought.

**Miffed.** After his first week (`life.miffed_after_days`, 7), if you vanish
for three hours or more in the daytime without a goodbye, he's a bit miffed
when you're back: one theatrical huff ("Oh, look who it is."), then it's over
the moment you talk. A goodbye, a night, a weekend away or the server being off
never count. `life.miffed = false` keeps him just glad.

**Goodbyes.** "Off to lunch", "night Kit", "heading home", "back in a bit" and
the like get one short, warm line, made locally even in cloud-first. It has no
question in it and nothing that makes leaving feel bad ("already?", "so soon",
"alone", "before you go..."). Research on companion apps found those hooks keep
people chatting out of guilt; Kit is glad of your plans instead. A line that
fails gets three goes, then a stock "Righto, see you soon." He remembers what
you said, for the hello when you're back.

**Missing you.** A day without seeing or hearing from you and he misses you a
bit. It shows if you message from your phone while you're away.

**Without the desk app** he can't tell you're away, so only a gap of three
hours or more since you last talked counts as being gone.

`life.homecoming = false` turns hellos (and miffs) off; he just carries on.

## Closeness

How well you two know each other is a word, never a score, and never said
aloud: getting to know you, warming up, at home, good mates, thick as thieves.
It starts at the first and grows a little with every good moment (chatting,
thanks, a laugh, answering his pipe-ups), at most a little each day, and
slower once you're close. Rudeness and ignored pipe-ups set it back a bit. It
never fades with time. His prompt says how it shows ("you're warming up to each
other: relaxed, with a bit of teasing"), and `kit life` shows the word.

## A game a day

At most once a day, in the daytime, when he's bored and you're at the PC, Kit
thinks of a small game and writes it in his notebook as something he wants to
bring up: a bet on today's top temperature (mornings), rate your lunch out of
ten (after lunch), a would-you-rather, finish the song line, or this-or-that.
His next pipe-up suggests it. Answer and it landed; ignore it and it flopped. A
game that flops three times without ever landing is retired (`GET /api/life`
lists them). `life.games = false` stops them.

## His own thoughts

Every eight minutes or so while you're at the PC (`life.think_every_minutes`),
Kit has a private thought: something he noticed, a question, an opinion
forming, a small worry, a joke he's saving for you. Something happening brings
one sooner: you come back to the PC, open something new, a build fails or
passes on screen, or a chat ends. The local model writes it as his inner voice,
from his self-sheet, his quirks, how he feels, what's on your screen, what he
remembers and what's been said today, and it may write nothing at all if
nothing comes to mind.

He doesn't think while you're talking to him, while he's asleep, or when
nobody's around, and never more than `life.thoughts_per_hour` times an hour.
Each thought is one quick call to the local model; nothing goes to the cloud.

A thought can:
- turn into something he **wants to say or ask** you. It presses harder the
  longer it waits, and his next pipe-up brings it up;
- change how he **feels**, with the reason;
- become an **opinion** he keeps.

Ask "what are you thinking about?" and he tells you his actual recent thoughts,
not an invented one. If nothing's been on his mind, he says so.

## Something for tomorrow

"Ask me tomorrow how the shutdown went" goes straight into his notebook as a
want that waits till the morning: it's due when quiet hours end
(`life.quiet_until`), and by then it has waited all night, so he brings it up
at his first chance. The same goes for a thought of his that starts with
"tomorrow", and for the things his nightly reflection says he'd like to bring
up. Once he's said it, in a pipe-up or in passing in a chat, he doesn't ask
again.

## His notebook

Facts in memory are about you. The notebook is Kit's own:

- **thoughts** from quiet moments; small ones fade after two weeks;
- **opinions** he's formed;
- **wants**: things he means to say or ask, until he does (or a week passes);
- **moments** worth keeping;
- a **journal** entry for each day;
- his **self-sheet**: who he thinks he is, in his own words, with every earlier
  version kept;
- his **quirks**, including the ones he dropped or you took away.

Thoughts, opinions, moments and the journal are in the knowledge index (the
`self` source, see [memory.md](memory.md)), so "what did you make of
yesterday?" recalls them like any memory. The memory page has a **Kit's
notebook** tab with all of it, where you can forget any entry, take a quirk
away or give it back, and go back to an earlier self-sheet.

## Each night, looking back

After midnight, once the day's summary is written, Kit reflects on the day. The
work model (Claude Sonnet unless you change `routing.work`) reads the day as
Kit: the conversation, the summary, his thoughts and feelings, his journal from
the days before, and what you undid lately. It writes:

- a **journal** entry, in his own words: what happened, what he noticed, how
  he felt and why, and how his quirks landed;
- his **self-sheet**, under 180 words: who he is, how he talks, his running
  jokes, how you two get on, what's on his mind. It goes in front of him every
  time he talks, in place of the persona's list of traits, so he grows a little
  each day. It changes slowly, and around the persona you gave him, never away
  from it;
- his **quirks**: usually the same, at most one dropped or picked up a night.
  One that has fallen flat for days running can go;
- up to three **opinions**, two **moments** and three things to **bring up
  tomorrow**.

The first time the brain starts, he writes his first self-sheet from the
persona. If you change the persona's traits later, he sees both until his next
reflection folds the change in.

`life.reflect_with` picks who writes it: `cloud` (the default: the work model,
about 2 cents a day, logged as spend, with the local model stepping in if the
cloud can't), `local` (free, but a small model writes a flatter diary), or
`off` (he doesn't reflect or change). If no model gives a readable answer, he
tries again an hour later, and after three tries he skips that day rather than
paying for it every hour. After time off, he catches up on the last three days
at most.

## Each week, a review you can undo

Once a week the expert model (Claude Opus unless you change `routing.expert`)
reads his self-sheet from a week ago and now, his journal, the opinions he
formed and the quirks he dropped, and writes a short review: what changed,
whether it still fits the persona you gave him, and anything that looks off.
It costs a few cents a week. Turn it off with `life.weekly_review = false`.

The review is on the notebook tab, under his self-sheet. Undo
anything there: go back to an earlier self-sheet, take a quirk away or give one
back. Nothing is deleted, and Kit is told what you undid, so his next
reflection doesn't do it again. A quirk you took away never comes back unless
you give it back.

## Piping up, with manners

When a want gets strong enough, Kit says something of his own accord. The words
are written by the local model on the spot, from what you're doing (the PC and
Chrome feed) and what he remembers, so you've never seen them before. How cheeky
he is depends on `life.cheek`: polite, friendly with a bit of cheek, or a
proper larrikin. He also picks three **quirks** for himself the first time he
starts (rating things out of ten, coffee counting, sports commentary when
bored...). They colour what he says, and they're his: his nightly reflection
may drop one that wore thin or pick up a new habit, one change a night at most.
`GET /api/life` shows them, if you want to know. It's more fun not to look.
The pool used to have a few about work (pumps, flowsheets, spreadsheets); a Kit
that picked one swaps it for an everyday one once, as if you'd taken it away.

When he has something he wants to bring up, a bored or lonely pipe-up shares
it, or failing that his newest thought. So what he says first comes from what
he's actually been thinking about. A pipe-up is one line with the actual thing
in it, not a teaser like "got a minute?". Nobody is waiting on it, so the whole
line is checked before it's shown: if any of it is something he's said lately,
he has two more goes, and if those repeat too he keeps quiet and tries again
after the usual gap. Answer him ("yeah, what's up?") and he's reminded what he
piped up about and why, so he tells you rather than saying the line again.

He never pipes up:
- in quiet hours (`life.quiet_from` to `life.quiet_until`, 10 pm to 7 am by default);
- while you're on a call (Teams, Zoom, Meet...) or presenting;
- while you're typing or clicking away. He waits for a natural pause;
- when you're away or the PC is locked;
- within 10 minutes of a chat, or more than `life.max_per_hour` times an hour.

If you ignore him, he sulks a little (a sigh) and waits twice as long next
time, then four times, then eight. Leaving the PC, or him dozing off, isn't
ignoring him: no sulk. Talking to him makes up for it. Say
**"shush"** or **"not now"** and he's quiet for an hour. "You can talk again"
lets him back, and so does "Quiet for an hour" in the tray menu.
`life.chattiness = 0` means he never speaks first but still fidgets.
`life.enabled = false` turns it all off.

## One brain, many bodies

Everything above lives in the brain (`kit.life` on the server), including when
Kit falls asleep and wakes up. The desk app, the chat and later the arm are
bodies: they listen to `/api/life/events` and act out what he decides, so
they always agree. The brain decides he's asleep after
`life.sleep_after_minutes` away (10 by default) or when the PC is locked, and
awake the moment the desk app reports you're back.

The desk app adds only reflexes, the way your body blinks without asking your
brain. They're instant and need nothing from the server:
- every 20 to 70 seconds (random) Glow glances at the window you're working in,
  as if reading over your shoulder;
- when the brain says he's asleep, he yawns, dozes off and slides down to lie on
  the bottom of the screen. When it says he's awake, he startles, perks up and
  climbs back to his spot.

Pipe-ups appear in his speech bubble and in the chat, so you can answer them.
If his face is hidden, they show as a Windows notification.

Some things get a **reaction** the moment they happen, before any answer, so
you can see he heard: he perks up when you're back, waves when you say goodbye,
wiggles at praise, droops when the cloud doesn't answer and perks up when its
answer arrives. These come as `react` events and play even mid-conversation,
where fidgets wait. While you type to him in the chat window, his face leans in
and listens.

## Why it stays unpredictable

1. **Wants, not actions.** You set how fast drives rise and what's allowed. When
   and what he does depends on you and the moment.
2. **The model writes the words** each time, from live context.
3. **Gestures are a vocabulary.** He picks among several for each mood, at
   random times, and on the arm each one is varied by mood and noise (below).
4. **Quirks he chose,** not you, and they change as he does.
5. **Hidden state.** Mood, feelings and why, sulking, curiosity about a
   particular thing, what he's been thinking. The same situation on a different
   day gives a different Kit.
6. **A self he writes.** His self-sheet changes a little each night, from what
   actually happened between you.

The one rule: don't watch `/api/life` all day. Let him surprise you.

## The arm (stage 9)

The same drives and events steer the body. The arm subscribes to
`/api/life/events` exactly as the desk app does:

| Kit's state | On the screen now | On the arm later |
|---|---|---|
| Asleep, you're away | eyes close, slides down the screen | lies down flat on the desk, slow breathing |
| You come back | startle, perk up, climbs back | lifts its head, stretches, turns to you (camera) |
| Bored | sighs, looks around | taps the desk, looks around the room, peers at things |
| Curious | peeks at your window | leans toward the monitor, tilts its head |
| Wants a chat | peeks, tilts | turns to look at you and holds it, then asks what you're doing |
| Sulky | sigh, looks away | turns away a little, droops |

Arm moves are recorded by hand once (armctl `record`). Each time one plays, his
mood scales its speed and size, a little random noise is added, and moves blend
into each other, so no two look the same.

## API

- `GET /api/life`: mood, feeling and why, drives, what he's thinking, what he
  wants to bring up now and later, quirks, snooze, and the life settings.
- `GET /api/life/events?after=N&wait=25`: fidgets, reactions, sleep and wake,
  and pipe-ups after event N; waits up to `wait` seconds for one.
- `POST /api/life/snooze {"minutes": 60}`: quiet for a while (0 lifts it).
- `GET /api/life/notebook`: his self-sheet and its earlier versions, weekly
  reviews, quirks (and retired ones), wants, thoughts, opinions, moments,
  journal, and what you undid.
- `DELETE /api/life/notebook/{id}`: forget a notebook entry.
- `POST /api/life/sheet/restore {"id": N}`: go back to an earlier self-sheet.
- `POST /api/life/quirks/retire {"quirk": "..."}` and
  `POST /api/life/quirks/restore {"quirk": "..."}`: take a quirk away or give
  it back.
- `POST /api/life/think`: have a thought now (for testing).
- `POST /api/life/reflect`: reflect on today so far, now (for testing; costs a
  few cents with `reflect_with = "cloud"`). Tonight's reflection replaces
  today's journal entry; the earlier one stays in its history.


## In conversation

The same state colours ordinary replies from the local model. Each turn
(`Life.voice`) the prompt says how Kit feels and why (bored, curious, missed
you, sleepy, sulky, chuffed because you called him a legend...), how cheeky to
be (`life.cheek`), sometimes which of his quirks to let show, what's been on
his mind lately (to bring up only if it fits), four example lines picked fresh
each time from your `persona.examples` and a built-in pool, and his own last
few lines so he doesn't repeat himself, how close you two are, and how long
since you talked. His self-sheet stands in for the
persona's list of traits, and up to `memory.own_memories` (3) entries from his
notebook are recalled if they're relevant. The mood is read before your message
resets it, so "I've been bored" is still true when he answers.

Your work is a job, not your whole life. Every prompt (chat, pipe-ups, his
thoughts and his nightly reflection) says so: everyday things (your day, food,
the weather, the weekend, music) come first, and work, code or engineering only
when you bring them up or they're plainly what you're busy with. The built-in
persona is written the same way; if your settings still had the old one, word
for word, it's read as the new one, and anything you wrote yourself is kept.
Edit it on the settings page (persona: backstory, traits, what he knows about
you, example lines). When the backstory or traits change, his next nightly
reflection brings his self-sheet in line with them.

He opens as "a small companion who lives on Dan's desk and is on Dan's side",
not an assistant, and the default rules make him an honest friend rather than a
yes-man: he says so kindly when you have a fact wrong, shows he got what you
told him before asking anything (one question at most, never one he knows the
answer to), takes your side when you have a moan (then one honest line if it
helps), and never makes you feel bad for leaving or being busy. Rules you wrote
yourself are kept; the old default three are read as the new seven. A cloud
model gets his mood, how close you are and the time line too, but not the
local model's coaching (examples, his last lines).

Ask him about himself ("why'd you go quiet?", "did you miss me?", "what can
you see?", "are you real?") and he's handed what's true right now: how he
feels and why, why he hasn't been piping up, and what he can sense (your PC's
windows and idle time, Chrome tabs, the time and the weather; no camera or
microphone yet). He owns his feelings, like missing you, but never claims to
be human.

He only hands chat to the cloud when it's a real question or job. News, a
moan, how you feel or a joke get his own answer, even about work, and so does
"what are you thinking about?". He only asks to add something to the register
when you named it.

## Two passes: deciding, then talking

With `ollama.speak_pass` on (the default), the local model answers in two
steps. First a quick JSON plan: his emotion, his gesture, and whether to look
something up, hand over to the cloud or remember something. Then his words, in
plain text, at a livelier setting (`ollama.speak_temperature`, `min_p`,
`top_k`, `top_p`, `repeat_penalty`, `repeat_last_n`; top_k 64 and top_p 0.95
are what Gemma's makers suggest). Small models sound stiff when they write speech inside JSON;
in plain text they sound more like themselves. He starts talking about half a
second later. His opening (whole sentences, six words or more, so a short
"You got a minute?" isn't mistaken for new) is checked first: if it's the same
as something he said lately, he's asked once more for something new, and the
repeat is never shown. He says three sentences at most. Anything after a blank
line is shown under his words in a grey box, but only if it's something to read
(code, a list or steps, a table, a link or a path, or a proper explanation);
another line of chat there is dropped, since in the box it looked like he was
answering himself. If he writes his plan again where his words should be
(`{"emotion": ..., "gesture": ...}`), it's dropped, never shown, and he's asked
again for plain words; JSON that got into earlier lines is kept out of what he
sees of the chat, so he doesn't copy it. Cloud models still answer in one piece.

`kit eval voice` compares local models on this: see
[stage-inner-life.md](stage-inner-life.md). `kit eval companion` checks the
goodbyes, hellos and honesty above: see
[stage-companion-1.md](stage-companion-1.md).

## Checking on him

- `kit life` shows his mood, how he feels and why, his drives, what he's
  thinking, what he wants to bring up (now and later), his quirks, why he
  isn't piping up right now (typing, quiet hours, just chatted, not bored
  enough yet...), how close you two are, whether you're away, a hello he
  still owes you, and your last goodbye.
- `kit life poke` makes him pipe up now, whatever his manners say. Handy for
  testing; the desk app shows it like any other pipe-up.
- `kit life think` makes him have a thought now.
- `kit life reflect` makes him reflect on today so far (a few cents).
- `kit life notebook` prints his notebook; the memory page shows it too.

On his own, with default settings, boredom needs about 25 quiet minutes with
you at the PC (not chatting, not mid-typing) before he speaks first.

A restart picks up where he left off: his drives, how he feels and why, how
long since you talked, whether he's sulking, what he's seen today, when he
last thought, whether he's asleep, when you were last at the PC, your last
goodbye and how close you are are saved in his memory. Twenty minutes or more
off is remembered as time he was switched off. Drives move on by however long he was
off, and a feeling keeps fading from when it began. After an hour or more off,
boredom and sulking start fresh.

## Turning him up

`life.chattiness` scales everything: how fast he gets bored, how long he
waits after a chat (about 7 minutes at 0.5, 2 at 1.0) and between pipe-ups.
From 0.8 he's properly chatty:

- he follows along: switching file, tab or window is worth a comment;
- he nags if you ignore him (twice, a few minutes apart), then sulks;
- now and then he butts in while you're typing, knowing full well;
- being ignored doesn't make him back off, it makes him nag.

He still never talks in quiet hours, on calls, while presenting, when you're
away, or while snoozed ("shush" or "not now" works for an hour). For the full
experience:

    kit config set life.chattiness 1
    kit config set life.max_per_hour 20
    kit config set life.cheek 0.9
