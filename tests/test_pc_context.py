"""What Kit sees of Dan's PC through the desk app, and how he uses it."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.memory import Memory
from kit.pc_context import PcContext, Snapshot
from kit.recall import Recall
from kit.server import create_app
from kit.settings_store import SettingsStore

AUTH = {"Authorization": "Bearer t"}


def snap(app="Visual Studio Code", title="pump.py - METTOOLS", idle=0, **extra):
    return Snapshot.model_validate(
        {
            "host": "DESK",
            "focus": {"app": app, "title": title} if app else None,
            "idle_seconds": idle,
            "windows": [
                {"app": app or "Explorer", "title": title},
                {"app": "Excel", "title": "Flotation.xlsx"},
                {"app": "Chrome", "title": "", "minimised": True},
            ],
            "system": {
                "cpu_percent": 12,
                "memory_percent": 63,
                "memory_used_gb": 10.1,
                "memory_total_gb": 16,
                "disks": [{"name": "C:", "free_gb": 120, "total_gb": 476}],
                "uptime_hours": 77,
                "busiest": [{"app": "Chrome", "cpu_percent": 8, "memory_mb": 1229}],
            },
            **extra,
        }
    )


def run(pc, clock, minutes, report):
    """The desk app reporting every 30 seconds for a while."""
    for _ in range(minutes * 2):
        clock.now += timedelta(seconds=30)
        pc.update(report)


def test_nothing_reported_means_no_line():
    pc = PcContext(Clock())
    assert pc.now_line("Dan") == ""
    assert "isn't running" in pc.detail("Dan")


def test_now_line_says_focus_how_long_and_whats_open():
    clock = Clock()
    pc = PcContext(clock)
    pc.update(snap())
    run(pc, clock, 12, snap(idle=90))
    line = pc.now_line("Dan")
    assert 'Visual Studio Code: "pump.py - METTOOLS", for 12 min.' in line
    assert "No keyboard or mouse for 2 min." in line
    assert "Also open: Excel, Chrome." in line


def test_focus_changes_build_the_hour_and_the_day():
    clock = Clock()
    pc = PcContext(clock)
    pc.update(snap())
    run(pc, clock, 20, snap())
    run(pc, clock, 10, snap("Excel", "Flotation.xlsx"))
    run(pc, clock, 2, snap("Excel", "Flotation.xlsx", idle=400))  # wandered off
    detail = pc.detail("Dan")
    assert '- Visual Studio Code: 20 min, on "pump.py - METTOOLS" (20 min)' in detail
    assert '- Excel: 10 min, on "Flotation.xlsx" (10 min)' in detail
    assert "away or paused: 2 min" in detail
    assert "Today so far, by app:" in detail
    assert "PC health: CPU 12%, memory 63% (10.1 of 16 GB), C: 120 GB free of 476" in detail
    assert "up 3.2 days. Busiest: Chrome 8% CPU 1.2 GB" in detail
    assert "- Chrome (minimised)" in detail


def test_a_gap_in_reports_is_not_counted_as_focus():
    clock = Clock()
    pc = PcContext(clock)
    pc.update(snap())
    clock.now += timedelta(hours=2)  # desk app closed, PC off
    assert "last seen at 09:00 AM" in pc.now_line("Dan")
    pc.update(snap())
    assert sum(s.minutes for s in pc.spans) < 1


def test_paused_and_locked_hide_the_screen():
    pc = PcContext(Clock())
    pc.update(snap(watching=False, windows=[], focus=None))
    assert "paused PC watching" in pc.now_line("Dan")
    pc.update(snap(locked=True))
    assert pc.now_line("Dan") == "Dan's PC is locked."


def test_paused_detail_keeps_earlier_focus_private():
    clock = Clock()
    pc = PcContext(clock)
    run(pc, clock, 20, snap())
    pc.update(snap(watching=False, windows=[], focus=None))
    detail = pc.detail("Dan")
    assert "paused watching" in detail
    assert "pump.py" not in detail and "Visual Studio Code" not in detail
    assert "Today so far" not in detail
    assert "PC health: CPU 12%" in detail and "Busiest" not in detail


def make_brain(paths, *outputs):
    memory = Memory(paths.state_dir / "memory.db", Clock())
    store = SettingsStore(paths)
    recall = Recall(memory, FakeEmbedder(), store.current)
    claude = FakeAnthropic()
    brain = Brain(
        store.current, memory, FakeModel(*outputs), make_cloud(memory, claude, key="k"), recall
    )
    return brain, memory, claude


@pytest.mark.parametrize(
    "question",
    [
        "what have I been doing for the last hour?",
        "is my PC struggling?",
        "look at what i have open on my PC",
        "what's open?",
    ],
)
def test_pc_questions_are_answered_locally_from_a_fresh_look(paths, question):
    brain, memory, claude = make_brain(paths, reply("Mostly the pump code."))
    brain.pc.update(snap())
    events = collect(brain.chat(question))
    assert "looked_at_pc" in [e["type"] for e in events]
    system = brain.model.calls[0][0]["content"]
    assert "Open windows (3):" in system and "PC health: CPU 12%" in system
    assert "ask_cloud" not in system  # the cloud can't see the PC, so no hand-off
    assert "- look_at_pc:" not in system  # already looked, so one answer, not two
    assert not claude.calls
    memory.close()


@pytest.mark.parametrize(
    "question", ["what have I been doing wrong with this pump calc?", "how's the thickener?"]
)
def test_other_questions_dont_look_at_the_pc(paths, question):
    brain, memory, _ = make_brain(paths, reply("Hmm."))
    brain.pc.update(snap())
    events = collect(brain.chat(question))
    assert "looked_at_pc" not in [e["type"] for e in events]
    assert "Open windows" not in brain.model.calls[0][0]["content"]
    memory.close()


def test_look_at_pc_action_shows_the_detail_then_answers(paths):
    memory = Memory(paths.state_dir / "memory.db", Clock())
    model = FakeModel(
        reply("Let me have a look.", action="look_at_pc"),
        reply("You've been in the pump code for a while."),
    )
    recall = Recall(memory, FakeEmbedder(), lambda: SettingsStore(paths).current())
    store = SettingsStore(paths)
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    brain.pc.update(snap())
    events = collect(brain.chat("Should I take a break?"))
    assert "looked_at_pc" in [e["type"] for e in events]
    system = model.calls[0][0]["content"]
    assert "- look_at_pc:" in system
    assert 'METTOOLS". Also open: Excel, Chrome.' in system
    assert "Open windows (3):" in model.calls[1][-1]["content"]
    assert [m.text for m in memory.recent(5)][-1] == "You've been in the pump code for a while."
    memory.close()


def test_without_the_desk_app_look_at_pc_is_not_offered(paths):
    memory = Memory(paths.state_dir / "memory.db", Clock())
    model = FakeModel(reply("Hi."))
    store = SettingsStore(paths)
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    collect(brain.chat("hi"))
    assert "look_at_pc" not in model.calls[0][0]["content"]
    memory.close()


def test_desk_app_reports_through_the_api(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, FakeModel(), make_cloud(memory, key="k"), recall)
    app = create_app(store, memory, brain, "t", summarise_every_s=None)
    with TestClient(app) as client:
        body = snap().model_dump()
        assert client.post("/api/pc/context", json=body).status_code == 401
        assert client.post("/api/pc/context", json=body, headers=AUTH).json() == {"ok": True}
        seen = client.get("/api/pc/context", headers=AUTH).json()
        assert seen["online"] and seen["snapshot"]["host"] == "DESK"
        assert "Visual Studio Code" in client.get("/api/status", headers=AUTH).json()["pc"]
        bad = {"focus": {"title": "no app"}}
        assert client.post("/api/pc/context", json=bad, headers=AUTH).status_code == 422
    memory.close()
