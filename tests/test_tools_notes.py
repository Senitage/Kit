"""The notes pack (kit.tools.notes): finding notes and tasks, changing a note only
when asked or after a yes, opening one in Obsidian, undo, the Sunday look-over and
``kit notes``."""

import asyncio
import os
from datetime import datetime

import pytest

from fakes import FakeAnthropic, collect, reply
from kit.cli import main
from kit.memory import Memory
from kit.settings import Settings
from kit.tools import ToolCall
from kit.tools.confirm import needs_yes
from kit.tools.notes import undo_dir
from tool_helpers import Clock, make

LIST = "# Shopping list\n\n## Hardware\n- [ ] order filament 📅 2026-10-07\n- [ ] sandpaper\n"
PLANNER = "# Holiday planner\n\nBroome in July.\n- [ ] book the car (due 20 Nov)\n"


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


@pytest.fixture
def vault(tmp_path):
    folder = tmp_path / "Notes"
    (folder / "Home").mkdir(parents=True)
    (folder / "Home" / "Shopping list.md").write_text(LIST, encoding="utf-8")
    (folder / "Holiday planner.md").write_text(PLANNER, encoding="utf-8")
    return folder


def settings(vault, **extra):
    return Settings.model_validate(
        {
            "memory": {"min_similarity": 0.3},
            "routing": {"mode": "cloud-only"},
            "nas": {"vault": str(vault)},
            **extra,
        }
    )


def notes_brain(memory, vault, claude=None, **extra):
    s = settings(vault, **extra)
    brain, _, claude = make(memory, settings=s, claude=claude)
    brain.notes.sync(s.nas)
    brain.tool_context.notes = True
    return brain, claude


def run(brain, tool, **args):
    return asyncio.run(brain.tools.run(ToolCall("1", tool, args)))


def test_finding_notes_and_listing_tasks(memory, vault):
    brain, _ = notes_brain(memory, vault)
    out = run(brain, "list_tasks")
    assert out.ok and out.text.splitlines() == [
        "Open tasks in Dan's notes (3):",
        "- order filament 📅 2026-10-07 (in Home/Shopping list, under Hardware, due Wed 07 Oct)",
        "- book the car (due 20 Nov) (in Holiday planner, under Holiday planner, due Fri 20 Nov)",
        "- sandpaper (in Home/Shopping list, under Hardware)",
    ]
    week = run(brain, "list_tasks", due="this week").text
    assert "filament" in week and "car" not in week and "sandpaper" not in week
    assert run(brain, "list_tasks", due="today").text == "No open tasks due today in Dan's notes."
    assert "car" in run(brain, "list_tasks", note="holiday").text
    assert "Broome in July" in run(brain, "find_notes", query="Broome").text


def test_what_asks_first(memory, vault):
    brain, _ = notes_brain(memory, vault)
    s, pack, tool = brain.settings(), brain.tools.packs["notes"], brain.tools.get
    brain.current_text = "add sandpaper to my shopping list"
    append = {"note": "Shopping list", "text": "- [ ] glue"}
    assert not needs_yes(tool("append_note"), pack, s, append)  # plainly asked for
    brain.current_text = "I'm out of glue"
    assert needs_yes(tool("append_note"), pack, s, append)  # his own idea: offered first
    for name, args in [
        ("edit_note", {"note": "Shopping list", "find": "sandpaper", "replace": "sanding discs"}),
        ("tick_task", {"task": "filament"}),
        ("undo_note", {}),
    ]:
        assert needs_yes(tool(name), pack, s, args), name


def test_a_plain_ask_adds_to_the_note_straight_away(memory, vault):
    claude = FakeAnthropic(
        answer=["", reply("Added.")],
        tool_calls=[
            [
                (
                    "append_note",
                    {"note": "Shopping list", "section": "Hardware", "text": "- [ ] glue"},
                )
            ]
        ],
    )
    brain, _ = notes_brain(memory, vault, claude)
    events = collect(brain.chat("put glue under Hardware in my shopping list note please"))
    changed = next(e for e in events if e["type"] == "note_changed")
    assert changed["note"] == "Home/Shopping list.md" and brain.pending_tool is None
    text = (vault / "Home" / "Shopping list.md").read_text(encoding="utf-8")
    assert text.endswith("- [ ] sandpaper\n- [ ] glue\n")
    assert "The notes vault: 2 notes." in str(claude.calls[0]["system"])  # its shape


def test_ticking_a_task_shows_the_change_and_waits_for_a_yes(memory, vault):
    claude = FakeAnthropic(
        answer=["", reply("Tick off order filament?"), reply("Ticked.")],
        tool_calls=[[("tick_task", {"task": "filament"})]],
    )
    brain, _ = notes_brain(memory, vault, claude)
    events = collect(brain.chat("tick off the filament task"))
    confirm = next(e for e in events if e["type"] == "confirm")
    assert "+- [x] order filament" in confirm["preview"]
    assert "The change, as it would be made" in str(claude.calls[1]["messages"])
    path = vault / "Home" / "Shopping list.md"
    assert path.read_text(encoding="utf-8") == LIST and brain.pending_tool is not None
    collect(brain.chat("yes"))
    assert "- [x] order filament" in path.read_text(encoding="utf-8")
    assert [t.title for t in memory.index.items("tasks") if "filament" in t.title] == []


def test_a_note_changed_between_the_ask_and_the_yes_is_read_again(memory, vault):
    brain, _ = notes_brain(memory, vault)
    args = {"note": "Shopping list", "find": "sandpaper", "replace": "sanding discs"}
    brain.tools.get("edit_note").preview(dict(args))  # shown with the question
    path = vault / "Home" / "Shopping list.md"
    path.write_text(LIST + "- [ ] Dan's own line\n", encoding="utf-8")
    os.utime(path, (1, 1))
    out = run(brain, "edit_note", **args)
    assert not out.ok and "changed since I showed you" in out.text and "Dan's own line" in out.text
    assert "sanding discs" not in path.read_text(encoding="utf-8")
    assert run(brain, "edit_note", **args).ok  # asked again, against the note as it is


def test_ticking_without_a_note_finds_the_one_note(memory, vault):
    brain, _ = notes_brain(memory, vault)
    assert run(brain, "tick_task", task="book the car").ok
    assert "- [x] book the car" in (vault / "Holiday planner.md").read_text(encoding="utf-8")
    out = run(brain, "tick_task", task="nothing like it")
    assert not out.ok and "no open task like" in out.text


def test_undo_is_offered_after_a_change_and_puts_it_back(memory, vault):
    brain, _ = notes_brain(memory, vault)
    offered = lambda: {t.name for t in brain.tools.offered(["notes"])}  # noqa: E731
    assert "undo_note" not in offered()
    run(brain, "tick_task", note="Shopping list", task="sandpaper")
    assert "undo_note" in offered() and (undo_dir(brain)).is_dir()
    out = run(brain, "undo_note")
    assert out.ok and "put Home/Shopping list.md back" in out.text
    assert (vault / "Home" / "Shopping list.md").read_text(encoding="utf-8") == LIST
    assert "sandpaper" in run(brain, "list_tasks").text  # back in the index too
    assert "undo_note" not in offered()


def test_a_new_note_and_opening_one_in_obsidian(memory, vault):
    from test_desk_commands import online, run_with_desk

    brain, _ = notes_brain(memory, vault)
    brain.current_text = "start a new note for the shed build"
    assert run(brain, "new_note", title="Shed build", text="Timber first.").ok
    assert "Timber first." in (vault / "Shed build.md").read_text(encoding="utf-8")
    online(brain)
    out, seen = run_with_desk(brain, "open_note", {"name": "shopping list"})
    url = f"obsidian://open?vault={vault.name}&file=Home/Shopping%20list"
    assert out.ok and seen[0][1]["kind"] == "open_url" and seen[0][1]["args"] == {"url": url}
    assert not run(brain, "open_note", name="nope").ok


def test_the_pack_and_its_lines_come_only_with_a_vault(memory, vault, paths):
    brain, _ = notes_brain(memory, vault)
    assert brain.tools.context(["notes"])[0] == "The notes vault: 2 notes."
    assert brain.tools.context(["core"]) == []
    bare, _, _ = make(memory)
    assert bare.tools.offered(["notes"]) == [] and bare.tools.context(["notes"]) == []


def test_the_sunday_look_over_writes_a_want_and_changes_nothing(memory, vault):
    old = vault / "Old.md"
    old.write_text("- [ ] renew the rego\n", encoding="utf-8")
    os.utime(old, (1e9, 1e9))
    brain, _ = notes_brain(memory, vault)
    assert brain.notes_tidy() == []  # a Monday
    memory.clock.now = datetime(2026, 10, 11, 9)
    lines = brain.notes_tidy()
    assert "renew the rego" in lines[0] and brain.notes_tidy() == []  # once a day
    want = brain.notebook.unsaid_wants()[-1]
    assert want.text.startswith("I had a look over Dan's notes this week (I changed nothing)")
    assert [e for e in brain.life.events_after(0) if e["type"] == "notes_tidy"]
    assert old.read_text(encoding="utf-8") == "- [ ] renew the rego\n"


def test_kit_notes_shows_tasks_shape_and_undoes(paths, vault, capsys):
    main(["init"])
    assert main(["config", "set", "nas.vault", str(vault)]) == 0
    capsys.readouterr()
    assert main(["notes"]) == 0
    assert "2 notes in" in capsys.readouterr().out
    assert main(["notes", "tasks"]) == 0
    assert capsys.readouterr().out.endswith("3 open tasks\n")
    assert main(["notes", "shape"]) == 0
    assert capsys.readouterr().out.startswith("The notes vault: 2 notes.")
    assert main(["notes", "undo"]) == 1
    assert "nothing of mine to undo" in capsys.readouterr().out
