"""Where Dan is talking to Kit from.

Every chat message says which way it came in: the desk app, the chat page,
the terminal, his phone, or (from stage 3) his voice at the desk. Kit is told
in each prompt, so he answers to suit: short and spoken for voice, short and
small-screen for the phone, and on the desk app he can take "this" to mean
what's on screen. Each message is stored with its channel, so earlier turns
from somewhere else are marked in the history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# A message that waited this long to be sent (typed while Kit was out of reach) is
# marked as old news in the prompt.
LATE_AFTER = timedelta(minutes=2)


@dataclass(frozen=True)
class Arrival:
    """How a message reached Kit, beyond its channel: whether it was said out loud,
    when it was written if it waited to be sent, and which body it came through."""

    spoken: bool = False
    sent_at: datetime | None = None
    body: str | None = None

    def meta(self) -> dict:
        """What's kept with the stored message (only what was set)."""
        out: dict = {}
        if self.body:
            out["body"] = self.body
        if self.sent_at is not None:
            out["sent_at"] = self.sent_at.isoformat(timespec="seconds")
        if self.spoken:
            out["spoken"] = True
        return out


# name: (how it's described, how Kit should answer there)
CHANNELS: dict[str, tuple[str, str]] = {
    "desk": (
        "typing in the desk app on their PC",
        "They're at the PC, so 'this' or 'it' probably means what's on their screen (below).",
    ),
    "voice": (
        "talking to you out loud at the desk",
        "Your words are spoken: keep it short and natural, and leave detail empty unless "
        "they ask to see something.",
    ),
    "phone": (
        "on their phone, probably away from the desk",
        "Keep it short for a small screen. Their PC isn't in front of them, so don't assume "
        "they can see it.",
    ),
    "web": ("typing on your chat page in a browser", ""),
    "home": ("typing on your page in their home_app website, in a browser", ""),
    "terminal": ("typing in the terminal", ""),
}
DEFAULT = "web"
SHORT = {
    "desk": "the desk app",
    "voice": "voice",
    "phone": "their phone",
    "web": "the chat page",
    "home": "your home_app page",
    "terminal": "the terminal",
}


def known(channel: str | None) -> str:
    """The channel's name if Kit knows it, else the chat page."""
    return channel if channel in CHANNELS else DEFAULT


def _ago(gap: timedelta) -> str:
    minutes = int(gap.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} minutes"
    hours = minutes // 60
    return "an hour" if hours == 1 else f"{hours} hours"


def channel_line(
    channel: str, owner: str, arrival: Arrival | None = None, now: datetime | None = None
) -> str:
    said, how = CHANNELS[known(channel)]
    line = f"{owner} is {said}. {how}".strip()
    if arrival is None:
        return line
    if arrival.spoken and known(channel) != "voice":
        line += " They're saying this out loud, not typing: keep it short and natural."
    if arrival.sent_at is not None and now is not None:
        sent = arrival.sent_at
        if now.tzinfo is None:  # compare like with like; a time without a zone is local
            sent = sent.astimezone().replace(tzinfo=None) if sent.tzinfo else sent
        else:
            sent = sent.astimezone(now.tzinfo)
        if now - sent >= LATE_AFTER:
            line += (
                f" They wrote this at {sent:%H:%M}, {_ago(now - sent)} ago, while they"
                " couldn't reach you, so it may be old news by now."
            )
    return line
