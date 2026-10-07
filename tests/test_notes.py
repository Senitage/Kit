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
