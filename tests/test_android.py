"""The Android app's side of the contract: it moves Kit's face with a Kotlin port of
kit.face.character, and draws its settings page from Kit's settings schema. Its tests
check the port against numbers made here and the page against a copy of the schema.

If a character sheet or a setting changes, rebuild both with
``python tests/test_android.py`` (the app's own tests then check they still agree).
"""

from __future__ import annotations

import json
from pathlib import Path

from kit.devices import pairing_link
from kit.face import character as characters
from kit.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
RESOURCES = ROOT / "android" / "core" / "src" / "test" / "resources"
REFERENCE = RESOURCES / "face_reference.json"
SCHEMA = RESOURCES / "settings_schema.json"
CHARACTERS = ("kit2d", "kit3d", "retro")
TIMES = (0.1, 0.37, 0.8)
STATES = ("sleeping", "offline", "listening", "thinking", "working")
EMOTIONS = ("neutral", "happy", "sad")


def reference() -> dict:
    """What the Kotlin port should get for each character: every pose, gesture moves
    at a few moments, how states bend a few poses, and the state glows and colours."""
    out = {}
    for name in CHARACTERS:
        c = characters.preset(name)
        out[name] = {
            "poses": {e: c.pose(e) for e in c.emotions},
            "gestures": {
                g: {"seconds": c.gesture_seconds(g), **{str(t): c.gesture_at(g, t) for t in TIMES}}
                for g in c.gestures
            },
            "states": {
                s: {e: c.state_pose(s, e, c.pose(e)) for e in EMOTIONS if e in c.emotions}
                for s in STATES
            },
            "glow": {s: c.state_glow(s) for s in ("idle", *STATES)},
            "colours": {e: c.mood_colour(e) for e in c.emotions},
        }
    return out


def _rounded(value):
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def test_face_reference_matches_the_sheets():
    saved = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert _rounded(saved) == _rounded(reference()), (
        "a character sheet changed: run `python tests/test_android.py` to rebuild "
        f"{REFERENCE.relative_to(ROOT).as_posix()}"
    )


def test_settings_schema_copy_is_current():
    saved = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert saved == Settings.model_json_schema(), (
        "a setting changed: run `python tests/test_android.py` to rebuild "
        f"{SCHEMA.relative_to(ROOT).as_posix()}"
    )


def test_pairing_link_is_what_the_app_reads():
    # The app's PairingLink.parse reads kit://pair?url=...&name=...&token=...
    link = pairing_link("http://192.168.1.50:8600/", "phone", "abc+/=")
    assert link.startswith("kit://pair?")
    assert "url=http%3A%2F%2F192.168.1.50%3A8600&" in link
    assert link.endswith("token=abc%2B%2F%3D")


if __name__ == "__main__":
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps(reference(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {REFERENCE}")
    SCHEMA.write_text(
        json.dumps(Settings.model_json_schema(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {SCHEMA}")
