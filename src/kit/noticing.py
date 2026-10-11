"""Small moments Kit's eyes catch that he feels something about (``life.seen_feelings``).

The eyes report about once a second what each person's face and hands are doing
(kit.scene_context). Most of it is too fleeting for a feeling: a blink isn't
sleepiness, and a flicker of a smile isn't a smile at him. This watches the
reports for the few moments worth one, held long enough to be real:

    waved          the eyes saw a wave                 he waves back, glad
    thumbs_up      a thumbs up, two reports running    a nod, pleased
    thumbs_down    a thumbs down, two reports running  a droop, a little put out
    smiled         smiling at him for two seconds      pleased: he brightens
    frowning       frowning in four of five reports    sympathetic, and a thought
    eyes_closing   eyes shut in four of five, late     a yawn, and bed on his mind

Only Dan counts: by name, or the one person in view when the eyes can't put a
name to them (it's Dan's desk). Each moment has its own wait before it can come
again, so a long smile is one moment, not sixty. ``kit.life`` decides what Kit
feels and does about each. Plain Python with no camera libraries.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from kit.scene_context import SceneReport, SeenPerson

SMILE_FOR = timedelta(seconds=2)  # a smile held this long is a smile at him
SMOOTH = 5  # reports a frown or closed eyes is judged over
OUT_OF = 4  # ...and must show in this many of them
THUMB_REPORTS = 2  # a thumb held up for this many reports in a row
FACING = {"facing the camera", ""}  # his eyes are the camera: looking at him
AGAIN = {  # the least time between two of the same moment
    "waved": timedelta(minutes=1),
    "thumbs_up": timedelta(minutes=1),
    "thumbs_down": timedelta(minutes=1),
    "smiled": timedelta(minutes=10),
    "frowning": timedelta(minutes=20),
    "eyes_closing": timedelta(minutes=30),
}


@dataclass(frozen=True)
class Moment:
    kind: str  # one of AGAIN's keys
    who: str  # Dan's name, as his eyes know him (or the owner's, for one unnamed person)


class Noticing:
    """Watches the eyes' reports for :class:`Moment`s (see the module notes)."""

    def __init__(self) -> None:
        self._smiling_since: datetime | None = None
        self._frowns: deque[bool] = deque(maxlen=SMOOTH)
        self._closed: deque[bool] = deque(maxlen=SMOOTH)
        self._thumbs: dict[str, int] = {}  # "thumbs up": reports in a row
        self._waving = False  # the wave already counted is still going
        self._last: dict[str, datetime] = {}  # moment kind: when it last came

    def see(
        self, report: SceneReport | None, owner: str, now: datetime, late: bool = False
    ) -> list[Moment]:
        """The moments in this report. ``late``: it's late at night, so closing eyes
        mean bed."""
        person = dan(report, owner)
        if person is None:
            self._reset()
            return []
        who = person.name or owner
        found: list[str] = []
        facing = person.face is not None and person.looking in FACING
        waving = "waving" in person.actions
        if waving and not self._waving:
            found.append("waved")
        self._waving = waving
        held = {g for g in person.gestures.values() if g in ("thumbs up", "thumbs down")}
        for gesture in ("thumbs up", "thumbs down"):
            count = self._thumbs.get(gesture, 0) + 1 if gesture in held else 0
            self._thumbs[gesture] = count
            if count == THUMB_REPORTS:
                found.append(gesture.replace(" ", "_"))
        if facing and "smiling" in person.expressions:
            self._smiling_since = self._smiling_since or now
            if now - self._smiling_since >= SMILE_FOR:
                found.append("smiled")
        else:
            self._smiling_since = None
        if person.face is not None:
            self._frowns.append("frowning" in person.expressions)
            self._closed.append("eyes closed" in person.expressions)
        if sum(self._frowns) >= OUT_OF:
            found.append("frowning")
        if late and sum(self._closed) >= OUT_OF:
            found.append("eyes_closing")
        moments = []
        for kind in found:
            last = self._last.get(kind)
            if last is None or now - last >= AGAIN[kind]:
                self._last[kind] = now
                moments.append(Moment(kind, who))
        return moments

    def _reset(self) -> None:
        """Nobody to watch (or not Dan): what was building up starts again."""
        self._smiling_since = None
        self._frowns.clear()
        self._closed.clear()
        self._thumbs.clear()
        self._waving = False


def dan(report: SceneReport | None, owner: str) -> SeenPerson | None:
    """Dan in this report: the person his eyes name as Dan, or the only person in
    view if they can't name them. None if he isn't there, or the eyes are off."""
    if report is None or report.off or not report.people:
        return None
    for p in report.people:
        if p.name and p.name.casefold() == owner.casefold():
            return p
    if len(report.people) == 1 and not report.people[0].name and not report.people[0].unknown:
        return report.people[0]
    return None
