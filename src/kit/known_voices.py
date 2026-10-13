"""The people Kit has been introduced to, as his ears know them (kit.hearing).

Like faces (kit.known_faces), each person is a name and a few voice prints: 512
numbers worked out from a few seconds of someone talking, from which no sound
can be rebuilt. They're kept in one file in Kit's data folder
(``state/voices.json``); ``version`` goes up with every change, so running ears
fetch them again. ``kit hearing enrol NAME`` adds them, ``kit hearing forget
NAME`` deletes them.
"""

from __future__ import annotations

from kit.known_faces import KnownFaces

VOICES_FILE = "voices.json"  # in the data folder's state folder
VOICE_SIZE = 512  # the speaker model's numbers (kit.hearing.models)


class KnownVoices(KnownFaces):
    size = VOICE_SIZE
