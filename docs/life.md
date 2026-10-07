# Kit's inner life

Kit isn't scripted. There's no list of "at 3 pm, say this" or "every 40 seconds,
play that". Instead he has a few **wants** that rise and fall on their own, and
what he does comes from those wants meeting whatever is happening at the time:
what you're doing, how long since you talked, the time of day, and whether you
ignored him last time. You wrote the rules, but you can't predict the moves.

## What drives him (`kit.life`, on the brain)

| Drive | Rises when | Falls when |
|---|---|---|
| Boredom | nobody talks to him; faster while you're at the PC | you talk to him, or he pipes up |
| Curiosity | you open an app or site he hasn't seen today | it fades over a few minutes |
| Wanting a chat | hours pass without a conversation | you talk |
| Energy | follows the clock: sleepy after 10:30 pm, a dip after lunch | |

Out of these comes a **mood** (content, bored, curious, lonely, sleepy, or sulky
after being ignored). Every half minute he may **fidget**: a gesture picked at
random from the ones that suit his mood. Sighs and looking around when he's
bored, peeking and leaning in when he's curious, yawns when he's sleepy. The
more bored he is, the more he fidgets.

## Piping up, with manners

When a want gets strong enough, Kit says something of his own accord. The words
are written by the local model on the spot, from what you're doing (the PC and
Chrome feed) and what he remembers, so you've never seen them before. How cheeky
he is depends on `life.cheek`: polite, friendly with a bit of cheek, or a
proper larrikin. He also picks three **quirks** for himself the first time he
starts (pump opinions, coffee counting, sports commentary when bored...). They
stay his, and they colour what he says. `GET /api/life` shows which ones he
chose, if you want to know. It's more fun not to look.

He never pipes up:
- in quiet hours (`life.quiet_from` to `life.quiet_until`, 10 pm to 7 am by default);
- while you're on a call (Teams, Zoom, Meet...) or presenting;
- while you're typing or clicking away. He waits for a natural pause;
- when you're away or the PC is locked;
- within 10 minutes of a chat, or more than `life.max_per_hour` times an hour.

If you ignore him, he sulks a little (a sigh) and waits twice as long next
time, then four times, then eight. Talking to him makes up for it. Say
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

## Why it stays unpredictable

1. **Wants, not actions.** You set how fast drives rise and what's allowed. When
   and what he does depends on you and the moment.
2. **The model writes the words** each time, from live context.
3. **Gestures are a vocabulary.** He picks among several for each mood, at
   random times, and on the arm each one is varied by mood and noise (below).
4. **Quirks he chose,** not you.
5. **Hidden state.** Mood, sulking, curiosity about a particular thing. The same
   situation on a different day gives a different Kit.

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

- `GET /api/life`: mood, drives, quirks, snooze, and the life settings.
- `GET /api/life/events?after=N&wait=25`: fidgets and pipe-ups after event N;
  waits up to `wait` seconds for one.
- `POST /api/life/snooze {"minutes": 60}`: quiet for a while (0 lifts it).


## In conversation

The same state colours ordinary replies from the local model. Each turn
(`Life.voice`) the prompt says how Kit feels (bored, curious, missed you,
sleepy, sulky...), how cheeky to be (`life.cheek`), sometimes which of his
quirks to let show, four example lines picked fresh each time from your
`persona.examples` and a built-in pool, and his own last few lines so he
doesn't repeat himself. The mood is read before your message resets it, so
"I've been bored" is still true when he answers.

## Checking on him

- `kit life` shows his mood, drives, quirks, and why he isn't piping up right
  now (typing, quiet hours, just chatted, not bored enough yet...).
- `kit life poke` makes him pipe up now, whatever his manners say. Handy for
  testing; the desk app shows it like any other pipe-up.

On his own, with default settings, boredom needs about 25 quiet minutes with
you at the PC (not chatting, not mid-typing) before he speaks first. A restart
of the brain starts his drives again from scratch.
