"""`kit docs check`: the stale rows of Where Kit Is Up To, found offline."""

from pathlib import Path

from kit.cli import main
from kit.docs_check import STATUS_NOTE, check, findings, landed

NOTE = """---
tags: [meet-kit, topic/status]
---

# Where Kit is up to

## At a glance

| Part | State | Notes |
|---|---|---|
| The brain | Done | [[Brain]] |
| The body feed | Open, pull request #36 | [[Bodies]] |
| Naps | Open, pull request #37 | [[Inner Life]] |
| The docs as a vault | Open, pull request #38 | [[How These Docs Work]] |
| A phone app | Open, pull request #46 | [[Phone App]] |
| This check | Open, pull request (number to come) | [[Commands]] |

## How we got here

| When | What landed | Pull requests |
|---|---|---|
| 6 Oct | Project skeleton | #1 |
| 7 Oct | Notes in the vault | #7, #8, #10 |
| 11 Oct | These docs as an Obsidian vault | #38 |

## Keeping this note true

Move its row from "Open" to "Done".
"""


def test_landed_numbers_come_from_the_history_table():
    assert landed(NOTE) == {1, 7, 8, 10, 38}
    assert landed("# Nothing\n\n| x | Open, pull request #3 |\n") == set()


def test_findings_name_the_stale_the_doubtful_and_the_unnumbered():
    found = {f.kind: f for f in findings(NOTE)}
    assert [str(f) for f in findings(NOTE)] == [
        "worth a look: The body feed (#36 is open but #38 landed after it)",
        "worth a look: Naps (#37 is open but #38 landed after it)",
        "stale: The docs as a vault (#38 is in the history table: it landed)",
        "needs its number: This check (the pull request is open)",
    ]
    assert "A phone app" not in str(findings(NOTE))  # #46 is newer than anything landed
    assert found["stale"].part == "The docs as a vault"


def test_check_prints_and_fails_only_on_stale_rows(tmp_path: Path):
    note = tmp_path / STATUS_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(NOTE, encoding="utf-8")
    lines: list[str] = []
    assert check(tmp_path, lines.append) == 1
    assert lines[-1] == "1 row(s) say open for a pull request that landed: move them to Done"
    note.write_text(
        NOTE.replace(
            "| The docs as a vault | Open, pull request #38 |", "| The docs as a vault | Done |"
        )
    )
    lines.clear()
    assert check(tmp_path, lines.append) == 0
    assert lines[-1] == "nothing stale; 3 to look at"
    assert check(tmp_path / "nowhere", lines.append) == 2


def test_kit_docs_check_runs_on_a_vault(paths, tmp_path: Path, capsys):
    note = tmp_path / STATUS_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(NOTE, encoding="utf-8")
    assert main(["docs", "check", "--vault", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "stale: The docs as a vault" in out and "needs its number: This check" in out


def test_the_repos_own_note_has_no_stale_row():
    assert not [
        f
        for f in findings(
            (Path(__file__).resolve().parents[1] / "docs" / STATUS_NOTE).read_text(encoding="utf-8")
        )
        if f.kind == "stale"
    ]
