"""Where Dan's phone says he is: home or out, worked out on the phone.

The phone app sends a short report when something changes: whether Dan's at
home or out, and how its battery is. Home or out is decided on the phone (it
remembers the Wi-Fi Dan marked as home), so no coordinates or addresses ever
reach Kit, only the word. Kit gets one line in his prompt, beside the PC's and
his eyes', so he knows Dan's out before Dan says so. The latest report from
each phone is kept in memory only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

STALE_AFTER = timedelta(hours=12)  # a phone that's gone quiet this long says nothing
FLAT_BELOW = 20  # battery percent worth a mention


class PhoneReport(BaseModel):
    """One report from the phone app."""

    place: Literal["home", "out", "unknown"] = "unknown"
    since: datetime | None = None  # when it became that
    battery: int | None = Field(None, ge=0, le=100)
    charging: bool | None = None


def since_words(since: datetime, now: datetime) -> str:
    """ "since 2:05 pm", or the day as well when it was before today."""
    if since.tzinfo is None and now.tzinfo is not None:
        since = since.replace(tzinfo=now.tzinfo)
    elif since.tzinfo is not None and now.tzinfo is None:
        since = since.astimezone().replace(tzinfo=None)
    else:
        since = since.astimezone(now.tzinfo) if since.tzinfo else since
    when = f"{since:%I:%M %p}".lstrip("0").lower()
    if since.date() != now.date():
        when = f"{since:%A} {when}"
    return f"since {when}"


class PhoneContext:
    """The latest report from each phone, and one line for Kit's prompt."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._reports: dict[str, tuple[PhoneReport, datetime]] = {}

    def report(self, phone: str, report: PhoneReport) -> None:
        self._reports[phone] = (report, self.clock())

    def latest(self) -> tuple[str, PhoneReport, datetime] | None:
        """The most recent report that isn't stale: (phone, report, when)."""
        now = self.clock()
        fresh = [(name, r, at) for name, (r, at) in self._reports.items() if now - at < STALE_AFTER]
        if not fresh:
            return None
        return max(fresh, key=lambda x: x[2])

    def place(self) -> str:
        found = self.latest()
        return found[1].place if found else "unknown"

    def now_line(self, owner: str) -> str:
        """One line for every prompt; empty until a phone has reported."""
        found = self.latest()
        if found is None:
            return ""
        _, report, at = found
        now = self.clock()
        line = ""
        if report.place == "out":
            line = f"{owner}'s phone says they're out"
            if report.since is not None:
                line += f" ({since_words(report.since, now)})"
            line += "."
        elif report.place == "home":
            line = f"{owner}'s phone says they're at home"
            if report.since is not None:
                line += f" ({since_words(report.since, now)})"
            line += "."
        if report.battery is not None and report.battery < FLAT_BELOW and not report.charging:
            line += f" Their phone's battery is nearly flat ({report.battery}%)."
        if line and now - at > timedelta(hours=1):
            line += f" (The phone last reported at {at:%I:%M %p}.)"
        return line.strip()

    def as_dict(self) -> dict:
        found = self.latest()
        return {
            "phone": found[0] if found else None,
            "place": self.place(),
            "report": found[1].model_dump(mode="json") if found else None,
            "at": found[2].isoformat(timespec="seconds") if found else None,
            "phones": {
                name: {**r.model_dump(mode="json"), "at": at.isoformat(timespec="seconds")}
                for name, (r, at) in self._reports.items()
            },
        }
