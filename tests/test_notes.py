import json

import pytest

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.memory import Memory
from kit.notes import NOTES, NoteError, Notes, Request, file_name, request
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
    events = collect(brain.chat("Remind me in my notes: Rex's dentist is in November"))
    assert "- note: when Dan asks you to take" in model.calls[0][0]["content"]
    assert "writing that down in Dan's notes" in model.speak_calls[0][-1]["content"]
    notice = next(e for e in events if e["type"] == "notice")
    assert notice["message"] == "Saved Dentist.md in your notes."
    assert "November" in (vault / "Dentist.md").read_text(encoding="utf-8")


def test_a_plain_note_request_is_done_before_the_model_answers(memory, vault):
    write(vault / "Holiday Planner.md", "Broome in July.")
    s = Settings.model_validate({"nas": {"vault": str(vault)}, "routing": {"mode": "local-heavy"}})
    # A small model that gets it wrong: plans a note for a question, and asks first.
    brain, model = make(
        memory,
        s,
        note_reply("Holiday Planner query", "Holiday Planner query"),
        reply("You sure you want me to write that down?"),
    )
    brain.notes.sync(s.nas)
    events = collect(brain.chat("Whats in my holday planner?"))
    assert "Broome in July." in model.calls[0][0]["content"]  # opened before answering
    assert next(e for e in events if e["type"] == "reading_note")["note"] == "Holiday Planner"
    assert not (vault / "Inbox").exists() and len(list(vault.glob("*.md"))) == 1  # no note

    events = collect(brain.chat("add book the car to my holiday planner"))
    notice = next(e for e in events if e["type"] == "notice")
    assert notice["message"] == "Added to Holiday Planner.md in your notes."
    assert "book the car" in (vault / "Holiday Planner.md").read_text(encoding="utf-8")
    assert "don't ask whether to write it down" in model.calls[1][0]["content"]

    collect(brain.chat("can you make a note: take the bins out on thursday"))
    assert (vault / "Take the bins out on thursday.md").exists()


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
        reply("Broome in July."),
    )
    brain.notes.sync(s.nas)
    events = collect(brain.chat("Are we sorted for the trip, going by my notes?"))
    system = model.calls[0][0]["content"]
    assert "- read_note:" in system and "Dan's notes (newest first): Holiday Planner." in system
    assert next(e for e in events if e["type"] == "reading_note")["note"] == "Holiday Planner"
    assert "Budget $4000" in model.calls[1][-1]["content"]


def test_note_requests_are_spotted_in_dans_words():
    names = ["Holiday Planner", "Projects/Kit", "Inbox/Shopping list"]
    assert request("Whats in my holday planner?", names) == Request("read", "Holiday Planner")
    assert request("put milk on the shopping list", names) == Request(
        "add", "Inbox/Shopping list", "milk"
    )
    assert request("add eggs to my grocery list", names) == Request("add", "grocery list", "eggs")
    assert request("note that the dog needs worming", names) == Request(
        "take", "", "The dog needs worming"
    )
    for chat in ["whats up kit", "what do you think about holidays", "yes", "tell me a joke"]:
        assert request(chat, names) is None


def test_kit_never_takes_a_note_dan_didnt_ask_for(memory, vault):
    s = Settings.model_validate({"nas": {"vault": str(vault)}, "routing": {"mode": "local-heavy"}})
    working_on = "Dan and Claude are giving Kit computer vision and a voice."
    brain, model = make(memory, s, note_reply("Kit upgrades", working_on))
    events = collect(brain.chat("yeah claude and i are working on giving you vision and a voice"))
    assert not list(vault.rglob("*.md"))  # nothing written
    assert "whether they'd like that written down" in model.speak_calls[0][-1]["content"]
    assert not any(e["type"] == "notice" for e in events)

    events = collect(brain.chat("yes"))
    assert (vault / "Kit upgrades.md").read_text(encoding="utf-8").endswith(working_on + "\n")
    said = "".join(e["text"] for e in events if e["type"] == "say")
    assert said == "Done, it's in Kit upgrades.md."


def test_a_note_offer_can_be_turned_down(memory, vault):
    s = Settings.model_validate({"nas": {"vault": str(vault)}, "routing": {"mode": "local-heavy"}})
    brain, _ = make(memory, s, note_reply("Bins", "Bins go out Thursday."))
    collect(brain.chat("the bins go out thursday now"))
    collect(brain.chat("nah"))
    collect(brain.chat("yes"))  # too late: the offer has gone
    assert not list(vault.rglob("*.md"))
