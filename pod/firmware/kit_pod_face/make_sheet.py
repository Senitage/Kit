"""Turn Kit's character sheet (kit2d.json) into kit2d_sheet.h for the Pod.

Run it again whenever the sheet changes (src/kit/face/characters/kit2d.json):

    python make_sheet.py [path/to/kit2d.json]

With no path it reads the sheet from this repo.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
SHEET = HERE.parents[2] / "src" / "kit" / "face" / "characters" / "kit2d.json"
POSE_KEYS = [
    "open", "squint", "tilt", "asym", "size", "look_x", "look_y", "blush", "head_tilt",
    "head_y", "mouth", "mouth_open", "mouth_o", "brow", "brow_up",
]
CHANNELS = ["dx", "dy", "rot", "sx", "sy", "scale", "look_x", "look_y", "open", "squint", "size", "wink"]
SHAPES = ["bump", "hold", "sin", "abs_sin", "line", "jolt"]


def f(v: float) -> str:
    s = f"{float(v):.4g}"
    return (s if any(c in s for c in ".e") else s + ".0") + "f"


def rgb(hex_: str) -> str:
    return "{" + ", ".join(str(int(hex_[i : i + 2], 16)) for i in (1, 3, 5)) + "}"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SHEET
    sheet = json.loads(src.read_text(encoding="utf-8"))
    look = sheet["looks"][sheet["use"]["robot"]]
    out = [f"// Made by make_sheet.py from {src.name} (\"{sheet['name']}\" v{sheet['version']}, look \"{sheet['use']['robot']}\"). Don't edit by hand.", "#pragma once", ""]

    for group in ("eyes", "glow", "brows", "mouth", "blush"):
        for k, v in look[group].items():
            if isinstance(v, (int, float)):
                out.append(f"const float {group.upper()}_{k.upper()} = {f(v)};")
    out.append(f"const float NECK = {f(look['neck'])};")
    rings = look["glow"]["rings"]
    out.append(f"const int N_RINGS = {len(rings)};")
    out.append("const float GLOW_RINGS[] = {" + ", ".join(f(r / 255) for r in rings) + "};")
    for k, v in look["colours"].items():
        out.append(f"const uint8_t COLOUR_{k.upper()}[3] = {rgb(v)};")
    out.append("")

    out.append("struct Pose { float " + ", ".join(POSE_KEYS) + "; };")
    base = sheet["pose_default"]

    def pose(over: dict) -> str:
        return "{" + ", ".join(f(over.get(k, base[k])) for k in POSE_KEYS) + "}"

    out.append(f"const Pose POSE_DEFAULT = {pose({})};")
    out.append("struct Mood { const char *name; Pose pose; uint8_t colour[3]; };")
    out.append("const Mood MOODS[] = {")
    colours = sheet.get("mood_colours", {})
    for name, over in sheet["poses"].items():
        c = colours.get(name, look["colours"]["eye"])
        out.append(f'  {{"{name}", {pose(over)}, {rgb(c)}}},')
    out.append("};")
    out.append("const int N_MOODS = sizeof(MOODS) / sizeof(MOODS[0]);")
    out.append("")

    # States: which pose (or none), values added and set, and the glow.
    out.append("struct StateRule { const char *name; const char *pose; const char *only_from; float glow;")
    out.append("  float add[" + str(len(POSE_KEYS)) + "]; bool has_set[" + str(len(POSE_KEYS)) + "]; float set[" + str(len(POSE_KEYS)) + "]; };")
    out.append("const StateRule STATES[] = {")
    for name, rule in sheet["states"].items():
        add = ", ".join(f(rule.get("add", {}).get(k, 0)) for k in POSE_KEYS)
        has = ", ".join("true" if k in rule.get("set", {}) else "false" for k in POSE_KEYS)
        st = ", ".join(f(rule.get("set", {}).get(k, 0)) for k in POSE_KEYS)
        p = f'"{rule["pose"]}"' if "pose" in rule else "nullptr"
        o = f'"{rule["only_from"]}"' if "only_from" in rule else "nullptr"
        out.append(f'  {{"{name}", {p}, {o}, {f(rule.get("glow", 1.0))}, {{{add}}}, {{{has}}}, {{{st}}}}},')
    out.append("};")
    out.append("const int N_STATES = sizeof(STATES) / sizeof(STATES[0]);")
    out.append("")

    # Gestures: each term is channel, amount and up to three shapes (type, a, b, c).
    out.append("enum Channel { " + ", ".join(f"CH_{c.upper()}" for c in CHANNELS) + ", N_CHANNELS };")
    out.append("enum ShapeType { SH_NONE, " + ", ".join(f"SH_{s.upper()}" for s in SHAPES) + " };")
    out.append("struct Shape { uint8_t type; float a, b, c; };")
    out.append("struct Term { uint8_t channel; float amount; Shape shapes[3]; };")
    out.append("struct Gesture { const char *name; float seconds; int first, count; };")
    terms, gestures = [], []
    for name, g in sheet["gestures"].items():
        if not g["moves"]:
            continue
        first = len(terms)
        for channel, items in g["moves"].items():
            for amount, *shapes in items:
                parts = []
                for sh in shapes:
                    args = list(sh[1:]) + [0, 0, 0]
                    if sh[0] == "bump" and len(sh) == 3:
                        args[2] = 0  # no cap
                    parts.append(f"{{SH_{sh[0].upper()}, {f(args[0])}, {f(args[1])}, {f(args[2])}}}")
                while len(parts) < 3:
                    parts.append("{SH_NONE, 0, 0, 0}")
                terms.append(f"  {{CH_{channel.upper()}, {f(amount)}, {{{', '.join(parts)}}}}},")
        gestures.append(f'  {{"{name}", {f(g["seconds"])}, {first}, {len(terms) - first}}},')
    out.append("const Term TERMS[] = {")
    out += terms
    out.append("};")
    out.append("const Gesture GESTURES[] = {")
    out += gestures
    out.append("};")
    out.append("const int N_GESTURES = sizeof(GESTURES) / sizeof(GESTURES[0]);")
    (HERE / "kit2d_sheet.h").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote kit2d_sheet.h: {len(sheet['poses'])} moods, {len(gestures)} gestures, {len(terms)} moves")


if __name__ == "__main__":
    main()
