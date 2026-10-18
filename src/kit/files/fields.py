"""What's worth knowing in a piece of a file, pulled out with plain rules so a later
search can narrow by year or quote an amount: the years it mentions (a financial
year counts as both), dollar amounts with the words around them, dates, ABNs,
reference numbers and the register's names. Pure functions, no I/O."""

from __future__ import annotations

import re

_YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
_FY = re.compile(r"\bFY\s?(20\d\d)\s?[-/]\s?(\d{2,4})\b", re.I)
_AMOUNT = re.compile(r"(?<![\w.])-?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d{2})?\b")
_ISO = re.compile(r"\b(20\d\d|19\d\d)-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b")
_DMY = re.compile(r"\b([0-2]?\d|3[01])/(0?[1-9]|1[0-2])/((?:19|20)\d\d)\b")
_ABN = re.compile(r"\b\d{2} ?\d{3} ?\d{3} ?\d{3}\b")
_REF = re.compile(
    r"\b(Invoice|Account|Assessment|Reference|Ref|Policy|Customer|Order)"
    r"(?:\s+(?:No\.?|Number|#))?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})\b",
    re.I,
)
AROUND = 40


def fields(text: str, names: list[str] | None = None) -> dict:
    years: set[int] = {int(y) for y in _YEAR.findall(text)}
    for start, end in _FY.findall(text):
        first = int(start)
        second = int(end) if len(end) == 4 else (first // 100) * 100 + int(end)
        years |= {first, second}
    amounts, lines = [], []
    for m in _AMOUNT.finditer(text):
        value = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        if m.group(0).startswith("-"):
            value = -value
        amounts.append(value)
        a, b = max(0, m.start() - AROUND), min(len(text), m.end() + AROUND)
        lines.append(" ".join(text[a:b].split()))
    dates = [f"{y}-{mo}-{d}" for y, mo, d in _ISO.findall(text)]
    dates += [f"{y}-{int(mo):02d}-{int(d):02d}" for d, mo, y in _DMY.findall(text)]
    abn = [" ".join(m.split()) for m in _ABN.findall(text) if len(m.replace(" ", "")) == 11]
    refs = [
        f"{kind.title()} {code}"
        for kind, code in _REF.findall(text)
        if any(c.isdigit() for c in code)
    ]
    lower = text.lower()
    found_names = [
        n for n in (names or []) if n and re.search(rf"\b{re.escape(n.lower())}\b", lower)
    ]
    out: dict = {}
    if years:
        out["years"] = sorted(years)
    if amounts:
        out["amounts"] = amounts
        out["amount_lines"] = lines
    if dates:
        out["dates"] = sorted(set(dates))
    if abn:
        out["abn"] = sorted(set(abn))
    if refs:
        out["references"] = sorted(set(refs))
    if found_names:
        out["names"] = found_names
    return out
