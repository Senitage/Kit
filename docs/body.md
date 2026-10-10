# Robot bodies

Kit's inner life lives in the brain (`kit.life`). A robot body only acts it out: it
shows his face and moves, and tells Kit when it's touched. The first body is the
Pod: an ESP32 with a 1.5" screen, a turn servo, a tilt servo and a pat sensor.

## The body feed

`GET /api/body/feed?after=N&wait=20` (with Kit's token) answers in plain text, one
thing per line, so a small board can read it without a JSON library:

```
face concerned        his resting face (Life.face(): strongest feeling, else mood)
asleep 0              1 while he's asleep
energy 0.62           how lively he is (the arousal dial, 0 flat .. 1 lively)
talk thinking         a chat turn has started
emotion happy         the reply's emotion
talk speaking 3.8     he's saying words that take about 3.8 s
talk done             the chat turn is over
fidget sigh           an idle move: a body may keep it to its face
gesture perk_up       a real reaction: a body plays it with its whole body
last 123              ask with after=123 next time
```

The first three lines and `last` come every time. Without `after` (a body that has
just started) the feed answers at once with no old events. With it, the feed waits
up to `wait` seconds for something new, so a body hears about it straight away.

Chat moments only went to the chat client before, so `kit.body.ChatMoments` copies
them into life's events where every body hears them.

`POST /api/body/touch`: Dan patted the body's head. Kit feels warm; the body shows the pat itself.

## How the Pod acts it out

The Pod's own rules (in its firmware, not here) keep its neck calm: the face is as
lively as the desk face, but the neck only moves for a glance round the room now
and then, something catching his eye, a real gesture or his mood's posture. Fidgets
stay on the screen. Liveliness (`energy`) sets how often he glances round and how
quickly his head moves.
