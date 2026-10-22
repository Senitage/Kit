"""Changing Dan's notes (kit.notes_edit), the tasks in them (kit.notes_tasks) and how
the vault is laid out (kit.notes.Notes.shape)."""

import json
import os
from datetime import date, datetime

import pytest

from fakes import Clock
from kit.memory import Memory
from kit.notes import NoteError, Notes, shape_lines
from kit.notes_edit import Append, Edit, New, NoteChanged, Tick, last_undo, undo
from kit.notes_tasks import TASKS, due_of, due_window, tasks_in
from kit.settings import NasSettings, NotesSettings

LOG = """---
tags: [work, riverbend]
status: active
---
# Riverbend log

## This Week
- [ ] check the spigot
- [x] order belts

## Later
- [ ] service the pump (due 20 Oct)
"""


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


@pytest.fixture
def vault(tmp_path):
    folder = tmp_path / "Notes"
    folder.mkdir()
    return folder


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def setup(memory, vault):
    write(vault / "Work" / "Riverbend log.md", LOG)
    nas = NasSettings(vault=str(vault))
    notes = Notes(memory.index, memory.clock)
    notes.sync(nas)
    return notes, nas


def test_adding_under_a_heading_shows_the_change_first(memory, vault, clock, tmp_path):
    notes, nas = setup(memory, vault)
    change = Append("Riverbend log", text="- [ ] clean the filter", section="this week")
    change.build(notes, nas)
    assert change.preview().splitlines() == [
        "@@ -9,2 +9,3 @@",
        " - [x] order belts",
        "+- [ ] clean the filter",
        " ",
    ]
    path = vault / "Work" / "Riverbend log.md"
    assert path.read_text(encoding="utf-8") == LOG  # nothing written yet
    applied = change.apply(nas, tmp_path / "undo", clock)
    text = path.read_text(encoding="utf-8")
    assert text.index("order belts") < text.index("clean the filter") < text.index("## Later")
    assert applied.shown == "Work/Riverbend log.md" and applied.undo_file.exists()

    with pytest.raises(NoteError, match="no heading 'Someday'.*This Week, Later"):
        Append("Riverbend log", text="x", section="Someday").build(notes, nas)
    end = Append("Riverbend log", text="- last line").build(notes, nas)
    assert end.after.endswith("(due 20 Oct)\n- last line\n")


def test_an_edit_or_a_tick_must_match_exactly_one_place(memory, vault):
    notes, nas = setup(memory, vault)
    edit = Edit("Riverbend log", find="check the spigot", replace="check the spigot twice")
    assert "+- [ ] check the spigot twice" in edit.build(notes, nas).preview()
    with pytest.raises(NoteError, match="isn't in"):
        Edit("Riverbend log", find="nothing like this", replace="x").build(notes, nas)
    with pytest.raises(NoteError, match="in 2 places"):
        Edit("Riverbend log", find="- [ ]", replace="x").build(notes, nas)

    tick = Tick("Riverbend log", task="SPIGOT").build(notes, nas)
    assert "+- [x] check the spigot" in tick.preview()
    with pytest.raises(NoteError, match="no open task like 'belts'"):
        Tick("Riverbend log", task="belts").build(notes, nas)  # already ticked
    with pytest.raises(NoteError, match="could be several tasks"):
        Tick("Riverbend log", task="the").build(notes, nas)
    with pytest.raises(NoteError, match="no note called"):
        Tick("Nowhere", task="x").build(notes, nas)


def test_a_note_edited_in_obsidian_meanwhile_is_not_written_over(memory, vault, clock, tmp_path):
    notes, nas = setup(memory, vault)
    change = Tick("Riverbend log", task="spigot").build(notes, nas)
    path = vault / "Work" / "Riverbend log.md"
    write(path, LOG + "- [ ] Dan's own new line\n")
    os.utime(path, (1, 1))
    with pytest.raises(NoteChanged, match="changed since I read it"):
        change.apply(nas, tmp_path / "undo", clock)
    assert "Dan's own new line" in path.read_text(encoding="utf-8")


def test_undo_puts_the_note_back_unless_it_changed_again(memory, vault, clock, tmp_path):
    notes, nas = setup(memory, vault)
    undo_dir = tmp_path / "undo"
    path = vault / "Work" / "Riverbend log.md"
    Tick("Riverbend log", task="spigot").build(notes, nas).apply(nas, undo_dir, clock)
    assert "- [x] check the spigot" in path.read_text(encoding="utf-8")
    _, side = last_undo(undo_dir)
    assert side["note"] == "Work/Riverbend log.md" and "ticked 'check the spigot'" in side["change"]
    said = undo(nas, undo_dir)
    assert said.startswith("put Work/Riverbend log.md back as it was before I ticked")
    assert path.read_text(encoding="utf-8") == LOG and last_undo(undo_dir) is None
    with pytest.raises(NoteError, match="nothing of mine to undo"):
        undo(nas, undo_dir)

    Tick("Riverbend log", task="spigot").build(notes, nas).apply(nas, undo_dir, clock)
    write(path, "Dan rewrote it all.\n")
    os.utime(path, (5, 5))
    with pytest.raises(NoteError, match="changed again .* would lose that edit"):
        undo(nas, undo_dir)
    assert path.read_text(encoding="utf-8") == "Dan rewrote it all.\n"


def test_only_the_newest_undo_files_are_kept(memory, vault, clock, tmp_path):
    notes, nas = setup(memory, vault)
    undo_dir = tmp_path / "undo"
    for minute in range(4):
        clock.now = datetime(2026, 10, 5, 9, minute)
        Append("Riverbend log", text=f"- line {minute}").build(notes, nas).apply(
            nas, undo_dir, clock, keep=2
        )
    assert len(list(undo_dir.glob("*.md"))) == 2 and len(list(undo_dir.glob("*.json"))) == 2


def test_a_new_note_from_a_template(memory, vault, clock, tmp_path):
    write(vault / "Templates" / "Project.md", "# {{title}}\nStarted {{date:YYYY-MM-DD}}\n")
    notes, nas = setup(memory, vault)
    new = New("", title="Shed build", folder="Projects", template="Project",
              text="Timber first.", templates_folder="Templates")  # fmt: skip
    new.build(notes, nas)
    assert new.mtime is None and "+# Shed build" in new.preview()
    applied = new.apply(nas, tmp_path / "undo", clock)
    assert applied.undo_file is None  # a new note isn't undone; nothing to put back
    assert (vault / "Projects" / "Shed build.md").read_text(encoding="utf-8") == (
        "# Shed build\nStarted 2026-10-05\n\nTimber first.\n"
    )
    with pytest.raises(NoteError, match="already a note called Shed build"):
        New("", title="Shed build", folder="Projects").build(notes, nas)
    with pytest.raises(NoteError, match="isn't inside the vault"):
        New("", title="x", folder="../../etc").build(notes, nas)
    with pytest.raises(NoteError, match="no template called Missing"):
        New("", title="y", template="Missing").build(notes, nas)


def test_tasks_and_their_due_dates():
    today = date(2026, 10, 5)
    assert due_of("pay rates 📅 2026-10-20", today) == date(2026, 10, 20)
    assert due_of("pay rates due:2026-11-01", today) == date(2026, 11, 1)
    assert due_of("pay rates (due 20 Oct)", today) == date(2026, 10, 20)
    assert due_of("rego (due 3 Jan)", today) == date(2027, 1, 3)
    assert due_of("rego (due 3 Jan 2026)", today) == date(2026, 1, 3)
    assert due_of("no date here", today) is None
    text = (
        "# Top\n- [ ] one\n```\n- [ ] in code\n```\n## Shed\n* [X] done\n- [ ] two 📅 2026-10-06\n"
    )
    tasks = tasks_in("Shed", text, today)
    assert [(t.text, t.heading, t.done, t.line_no) for t in tasks] == [
        ("one", "Top", False, 2),
        ("done", "Shed", True, 7),
        ("two 📅 2026-10-06", "Shed", False, 8),
    ]
    assert tasks[2].line() == "two 📅 2026-10-06 (in Shed, under Shed, due Tue 06 Oct)"
    monday = datetime(2026, 10, 5, 9)
    assert due_window("this week", monday) == (None, date(2026, 10, 11))
    assert due_window("next week", monday) == (date(2026, 10, 12), date(2026, 10, 18))
    assert due_window("overdue", monday) == (None, date(2026, 10, 4))
    assert due_window("this month", monday) == (None, date(2026, 10, 31))
    assert due_window("", monday) == (None, None)


def test_open_tasks_are_kept_in_step_with_the_vault(memory, vault):
    notes, nas = setup(memory, vault)
    items = memory.index.items(TASKS)
    assert sorted(t.title for t in items) == ["check the spigot", "service the pump (due 20 Oct)"]
    pump = next(t for t in items if "pump" in t.title)
    assert pump.meta["note"] == "Work/Riverbend log" and pump.meta["due"] == "2026-10-20"
    assert pump.meta["heading"] == "Later"
    path = vault / "Work" / "Riverbend log.md"
    write(path, LOG.replace("- [ ] check the spigot", "- [x] check the spigot"))
    os.utime(path, (10, 10))
    notes.sync(nas)
    assert [t.title for t in memory.index.items(TASKS)] == ["service the pump (due 20 Oct)"]
    path.unlink()
    notes.sync(nas)
    assert memory.index.items(TASKS) == []


def test_the_vaults_shape_is_read_from_its_notes_and_obsidian(memory, vault):
    write(vault / ".obsidian" / "daily-notes.json", json.dumps({"folder": "Daily"}))
    write(vault / ".obsidian" / "templates.json", json.dumps({"folder": "Templates"}))
    write(vault / "Home.md", "---\ntags: [hub]\n---\nSee [[Shed]] and [[Garden]].")
    write(vault / "Projects" / "Shed.md", "---\ntags: [project]\nstatus: on\n---\n[[Garden]]")
    write(vault / "Projects" / "Garden.md", "---\ntags: [project]\n---\nTomatoes.")
    write(vault / "Daily" / "2026-10-05.md", "Quiet day. [[Shed]]")
    notes = Notes(memory.index, memory.clock)
    nas = NasSettings(vault=str(vault))
    notes.sync(nas)
    shape = notes.shape(nas)
    assert shape.notes == 4 and dict(shape.folders) == {"Projects": 2, "Daily": 1}
    assert shape.daily_folder == "Daily" and shape.daily_format == "YYYY-MM-DD"
    assert shape.templates == "Templates" and shape.tags[0] == ("project", 2)
    assert shape.properties == ["status"] and set(shape.hubs) == {"Garden", "Shed"}
    lines = shape_lines(shape)
    assert lines[0] == "The notes vault: 4 notes." and len(lines) <= 8
    assert "Daily notes go in Daily, named like YYYY-MM-DD." in lines
    own = notes.shape(nas, NotesSettings(daily_folder="Journal", templates_folder="T"))
    assert own.daily_folder == "Journal" and own.templates == "T"


def test_the_tidy_report_changes_nothing(memory, vault, clock):
    write(vault / "Old.md", "- [ ] renew the rego")
    write(vault / "Alone.md", "Nothing links here.")
    write(vault / "Shopping list.md", "milk")
    write(vault / "Shopping lists.md", "eggs")
    for name in ("Old.md", "Alone.md"):
        os.utime(vault / name, (1e9, 1e9))
    notes = Notes(memory.index, memory.clock)
    notes.sync(NasSettings(vault=str(vault)))
    lines = notes.tidy_report(datetime(2026, 10, 5, 9))
    assert lines[0] == "1 open tasks in notes untouched for a month: renew the rego"
    assert "Alone" in lines[1] and lines[2].startswith("names that look alike: Shopping list")
    assert (vault / "Old.md").read_text(encoding="utf-8") == "- [ ] renew the rego"
