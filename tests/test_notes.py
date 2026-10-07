import json

import pytest

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud
from kit.brain import Brain
from kit.memory import Memory
from kit.notes import NOTES, NoteError, Notes, file_name
from kit.recall import Recall
from kit.settings import NasSettings, Settings


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


def note_reply(title, text, say="Noted."):
    return json.dumps(
        {
            "emotion": "happy",
            "segments": [{"say": say, "gesture": "nod"}],
            "action": {"kind": "note", "text": text, "title": title},
        }
    )


def test_a_note_is_a_markdown_file_in_the_vault(memory, vault):
    notes = Notes(memory.index, memory.clock)
    saved = notes.take(NasSettings(vault=str(vault)), "Fridge", "Call Harvey Norman re warranty.")
    assert saved.path == vault / "Fridge.md" and not saved.added
    text = saved.path.read_text(encoding="utf-8")
    assert text.startswith("---\ncreated: 2026-10-05T09:00\ntags: [kit]\n---\n")
    assert text.endswith("Call Harvey Norman re warranty.\n")
    item = memory.index.items(NOTES)[0]
    assert (item.title, item.ref) == ("Fridge", "Fridge.md")


def test_same_title_adds_to_the_note(memory, vault, clock):
    notes = Notes(memory.index, memory.clock)
    nas = NasSettings(vault=str(vault), notes_folder="Inbox")
    notes.take(nas, "Shopping list", "- milk")
    clock.now = clock.now.replace(hour=17, minute=30)
    saved = notes.take(nas, "Shopping list", "- bread")
    assert saved.added and saved.shown == "Inbox/Shopping list.md"
    text = saved.path.read_text(encoding="utf-8")
    assert text.index("- milk") < text.index("**Mon 05 Oct 2026, 17:30**") < text.index("- bread")


def test_titles_become_safe_file_names(clock):
    assert file_name("Pump: P-101 / seal?", clock()) == "Pump P-101 seal.md"
    assert file_name("../../etc/passwd", clock()) == "etc passwd.md"
    assert file_name("  ", clock()) == "Note 2026-10-05 0900.md"
    assert file_name("con", clock()) == "con note.md"


def test_notes_stay_inside_the_vault(memory, vault):
    notes = Notes(memory.index, memory.clock)
    with pytest.raises(NoteError, match="isn't inside the vault"):
        notes.take(NasSettings(vault=str(vault), notes_folder="../elsewhere"), "x", "y")
    with pytest.raises(NoteError, match="no notes folder"):
        notes.take(NasSettings(), "x", "y")
    with pytest.raises(NoteError, match="is the NAS mounted"):
        notes.take(NasSettings(vault=str(vault / "gone")), "x", "y")


def make(memory, settings, *outputs):
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), lambda: settings)
    return Brain(lambda: settings, memory, model, make_cloud(memory, key="k"), recall), model


def test_kit_takes_a_note_when_asked(memory, vault):
    s = Settings.model_validate({"nas": {"vault": str(vault)}, "routing": {"mode": "local-heavy"}})
    brain, model = make(memory, s, note_reply("Dentist", "Book Rex's dentist for November."))
    events = collect(brain.chat("Take a note: book the dentist for November"))
    assert "- note: when Dan asks you to take" in model.calls[0][0]["content"]
    assert "writing that down in Dan's notes" in model.speak_calls[0][-1]["content"]
    notice = next(e for e in events if e["type"] == "notice")
    assert notice["message"] == "Saved Dentist.md in your notes."
    assert "November" in (vault / "Dentist.md").read_text(encoding="utf-8")


def test_without_a_vault_kit_says_the_note_was_not_saved(memory):
    s = Settings.model_validate({"routing": {"mode": "local-heavy"}})
    brain, model = make(memory, s, note_reply("Dentist", "Book the dentist."))
    events = collect(brain.chat("Take a note: book the dentist"))
    assert "- note:" not in model.calls[0][0]["content"]
    notice = next(e for e in events if e["type"] == "notice")
    assert notice["message"].startswith("The note wasn't saved: no notes folder")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_whole_vault_is_read_and_kept_in_step(memory, vault):
    write(vault / "Holiday Planner.md", "---\ntags: [trip]\n---\nBroome in July.\n## Budget\n$4000")
    write(vault / "Projects" / "Kit.md", "Desk robot arm.")
    write(vault / ".obsidian" / "workspace.md", "settings")
    write(vault / ".SynologyWorkingDirectory" / "x.md", "sync junk")
    notes = Notes(memory.index, memory.clock)
    nas = NasSettings(vault=str(vault))
    assert notes.sync(nas) == (2, 0)
    items = memory.index.items(NOTES)
    assert {i.title for i in items} == {"Holiday Planner", "Holiday Planner > Budget", "Kit"}
    assert "tags" not in " ".join(i.text for i in items)  # frontmatter left out
    assert notes.sync(nas) == (0, 0)  # nothing changed, nothing re-read
    (vault / "Projects" / "Kit.md").unlink()
    assert notes.sync(nas) == (0, 1)
    assert notes.names() == ["Holiday Planner"]
    assert notes.sync(NasSettings(vault=str(vault / "gone"))) == (0, 0)  # NAS down: keep all
    assert notes.names() == ["Holiday Planner"]


def test_a_note_is_read_by_name_or_path(memory, vault):
    write(vault / "Projects" / "Kit.md", "---\ncreated: x\n---\nDesk robot arm.")
    notes = Notes(memory.index, memory.clock)
    nas = NasSettings(vault=str(vault))
    notes.sync(nas)
    assert notes.read(nas, "kit") == ("Projects/Kit.md", "Desk robot arm.")
    assert notes.read(nas, "Projects/Kit.md")[0] == "Projects/Kit.md"
    with pytest.raises(NoteError, match="no note called Fishing"):
        notes.read(nas, "Fishing")


def test_adding_to_a_note_elsewhere_in_the_vault(memory, vault):
    write(vault / "Holiday Planner.md", "Broome in July.")
    notes = Notes(memory.index, memory.clock)
    nas = NasSettings(vault=str(vault), notes_folder="Inbox")
    notes.sync(nas)
    saved = notes.take(nas, "holiday planner", "Book the car.")
    assert saved.added and saved.shown == "Holiday Planner.md"
    assert notes.take(nas, "Projects/Kit ideas", "A light head.").shown == "Projects/Kit ideas.md"
    assert notes.take(nas, "../../outside", "x").shown == "Inbox/outside.md"
    hits = memory.index.word_search("car", [NOTES], 5)
    assert hits and memory.index.get(hits[0]).ref == "Holiday Planner.md"  # re-read


def test_an_empty_note_takes_dans_words(memory, vault):
    s = Settings.model_validate({"nas": {"vault": str(vault)}, "routing": {"mode": "local-heavy"}})
    brain, _ = make(memory, s, note_reply("", ""))
    collect(brain.chat("take a note for me stating that you are testing notes"))
    (saved,) = vault.glob("*.md")
    assert saved.read_text(encoding="utf-8").endswith("You are testing notes\n")


def test_kit_opens_a_note_before_answering(memory, vault):
    write(vault / "Holiday Planner.md", "Broome in July. Budget $4000.")
    s = Settings.model_validate({"nas": {"vault": str(vault)}, "routing": {"mode": "local-heavy"}})
    brain, model = make(
        memory,
        s,
        json.dumps(
            {
                "emotion": "curious",
                "segments": [{"say": "Let me open it.", "gesture": "nod"}],
                "action": {"kind": "read_note", "text": "Holiday Planner"},
            }
        ),
        json.dumps(
            {
                "emotion": "happy",
                "segments": [{"say": "Broome in July.", "gesture": "nod"}],
                "action": {"kind": "none", "text": ""},
            }
        ),
    )
    brain.notes.sync(s.nas)
    events = collect(brain.chat("What's in my holiday planner?"))
    system = model.calls[0][0]["content"]
    assert "- read_note:" in system and "Dan's notes (newest first): Holiday Planner." in system
    assert next(e for e in events if e["type"] == "reading_note")["note"] == "Holiday Planner"
    assert "Budget $4000" in model.calls[1][-1]["content"]
