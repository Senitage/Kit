"""Where Dan is talking to Kit from.

Every chat message says which way it came in: the desk app, the chat page,
the terminal, his phone, or (from stage 3) his voice at the desk. Kit is told
in each prompt, so he answers to suit: short and spoken for voice, short and
small-screen for the phone, and on the desk app he can take "this" to mean
what's on screen. Each message is stored with its channel, so earlier turns
from somewhere else are marked in the history.
"""

from __future__ import annotations

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


def channel_line(channel: str, owner: str) -> str:
    said, how = CHANNELS[known(channel)]
    return f"{owner} is {said}. {how}".strip()
