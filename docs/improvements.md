# Future improvements

Things Dan has asked for that aren't built yet, with what was seen and ideas
for fixing them. Pick them up in the stage they fit.

## Check-ins while Kit is busy (from stage 1 testing, 2026-10-06)

Dan wants Kit to answer "how are you going?" during a slow cloud answer like a
real character: "give me a sec", getting genuinely more annoyed the more he
asks, never repeating itself.

What stage 1 does now: while a job runs, short messages count as checking in,
and the local model gets a note with the question, the time so far, the steps
done, how many times Dan has asked, and a matching level of patience.

What testing showed (asking "think hard about Australian immigration", then
"kit", "anything", "hey", "still?", "hey"):

- Kit repeats itself almost word for word ("Still on the immigration one.
  Been 12 seconds."), even when told not to.
- It copies made-up progress from its own earlier replies ("Just got the
  first hit"), because those replies are in the history it reads.
- The escalation shows only in the emotion tag (tired, droop), not in the
  words.

Ideas:

- Leave earlier check-in replies out of the history the model reads, or
  list them as "lines you've already used", so it can't copy them.
- Raise the temperature for check-in replies only.
- Drive the tone from kit.life's mood and drives (stage 2), so patience is
  real state that builds and fades, not a count in a prompt.
- At the start of a job, have the cloud model write a handful of in-character
  progress lines for that question, to use as seeds.
- Give real progress from streaming (search queries and pages opened as
  they happen, for every provider), so there's something true to say.
- Add a `kit eval` case: five check-ins in a row must give five different
  lines and escalate.

## Desk app chat window looks (from stage 2 testing, 2026-10-07)

Dan: the desk app's chat window works but needs aesthetic work. Worth a
design pass before the desk app is used daily: spacing, fonts, message
bubbles, and matching the Glow face's look. Ask Dan what bothers him most
before starting.

## Kit's personality in chat (from stage 2 testing, 2026-10-07)

Dan: "Kit doesn't have a personality yet." The local model copies the persona
examples word for word ("Coffee first, or straight into it?") and picked up a
catchphrase from its own recalled replies ("You're the one with the API key").
The prompt now says examples show tone only and old wording isn't to be
reused, and `kit new-chat` / `kit memory forget` clear a stuck line, but the
replies are still flat.

Done (Dan said "do it now"): every local reply now gets kit.life's mood
(before the chat resets it), the `life.cheek` style, now and then one of
Kit's quirks, four examples drawn fresh each turn from Dan's own plus a
built-in pool (`kit.life.VOICE_LINES`), and Kit's last six lines with "don't
repeat these". See docs/life.md.

Still open:

- Detect a reply that repeats one of Kit's last few lines and regenerate it.
- Try a bigger model for the chat role (Sonnet, or a larger local model on
  a 3090) and compare with `kit eval replies`.
