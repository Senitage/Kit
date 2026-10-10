"""Kit's robot bodies: what a body needs from the brain to act Kit out.

The brain decides what Kit feels and does; a body only plays it (see docs/body.md).
A small body such as the Pod (an ESP32 with a screen and two servos) can't do much
parsing, so it reads one plain-text feed: a few lines with his resting face, whether
he's asleep, how lively he is, and what just happened (a reply's emotion, talking,
a fidget). It long-polls ``GET /api/body/feed`` and sends pats to ``POST
/api/body/touch``.

Chat moments (thinking, a reply's emotion, talking) only reach the chat client, so
:class:`ChatMoments` copies them into life's events where every body hears them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kit.life import Life

WORDS_PER_SECOND = 2.6  # about how fast he talks, for how long a body moves its mouth
TALK_MIN_S, TALK_MAX_S = 1.0, 30.0
# Events a body hears about, as feed lines. Fidgets are idle moves a body may keep to
# its face; gestures (reactions) are real moments it plays with its whole body.
GESTURE_EVENTS = {"fidget": "fidget", "react": "gesture"}


def talk_seconds(text: str) -> float:
    return round(min(TALK_MAX_S, max(TALK_MIN_S, len(text.split()) / WORDS_PER_SECOND)), 1)


class ChatMoments:
    """Tells bodies about one chat turn as it happens: he's thinking from the start,
    then the reply's emotion and the words he says (with roughly how long they take)."""

    def __init__(self, life: Life) -> None:
        self.life = life
        self.felt = False
        life.publish({"type": "talk", "state": "thinking"})

    def see(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "mood" and event.get("emotion"):
            self._emotion(event["emotion"])
        elif kind == "reply":  # some replies carry their emotion only at the end
            self._emotion((event.get("reply") or {}).get("emotion") or "")
        elif kind == "say" and event.get("text"):
            seconds = talk_seconds(event["text"])
            self.life.publish({"type": "talk", "state": "speaking", "seconds": seconds})

    def done(self) -> None:
        """The turn's over: a body stops thinking (talking runs out on its own)."""
        self.life.publish({"type": "talk", "state": "done"})

    def _emotion(self, emotion: str) -> None:
        if emotion and not self.felt:
            self.felt = True
            self.life.publish({"type": "emotion", "emotion": emotion})


def _line(event: dict) -> str | None:
    kind = event.get("type")
    if kind in GESTURE_EVENTS and event.get("gesture"):
        return f"{GESTURE_EVENTS[kind]} {event['gesture']}"
    if kind == "emotion":
        return f"emotion {event['emotion']}"
    if kind == "talk":
        seconds = event.get("seconds")
        return f"talk {event['state']}" + (f" {seconds}" if seconds else "")
    return None


def feed(life: Life, events: list[dict]) -> str:
    """The body feed: Kit's state now, then a line for each of ``events`` a body can
    show, then the last event's id to ask from next time."""
    state = life.state()
    lines = [
        f"face {state['mood'] == 'asleep' and 'sleepy' or state['face']}",
        f"asleep {1 if state['mood'] == 'asleep' else 0}",
        f"energy {round(life.arousal, 2)}",
    ]
    lines += [line for e in events if (line := _line(e))]
    lines.append(f"last {state['last_event']}")
    return "\n".join(lines) + "\n"


def touched(life: Life, owner: str) -> None:
    """Dan patted the body's head: Kit feels warm. The body that was patted shows it
    itself, at once, so no gesture is sent back."""
    life.feel("warm", f"{owner} patted your head", 0.5, show=False)
