"""What Dan did on the PC, day by day (kit.activity), and the code projects Kit
knows (kit.projects), with the pc pack's tools that read them."""

import asyncio
import subprocess
from datetime import date, datetime, timedelta

import pytest

from kit.activity import ACTIVITY, activity_item, days_meant, recent_work, write_days
from kit.memory import Memory
from kit.pc_context import Span
from kit.projects import PROJECTS, Projects, pc_path
from kit.settings import Settings
from kit.tools import ToolCall
from tool_helpers import Clock, make

MONDAY = date(2026, 10, 5)


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-06T09:00:00"))
    yield m
    m.close()


def at(hour, minute=0, day=MONDAY):
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute)


SPANS = [
    Span("Excel", "riverbend-costs.xlsx - Excel", at(9), at(10, 30)),
    Span("VS Code", "pump.py - Pod - Visual Studio Code", at(10, 30), at(12)),
    Span("Chrome", "Rates - Google Chrome", at(12), at(12, 20), site="council.example"),
    Span("Notepad", "x.txt - Notepad", at(12, 20), at(12, 21)),  # too short to mention
    Span("", "", at(12, 21), at(13)),  # away
]


def test_a_day_is_one_paragraph_of_apps_files_sites_and_projects(memory):
    brain, _, _ = make(memory)
    brain.register.add("Pod", "project")
    recent = [
        {"name": "flot.xlsx", "when": "2026-10-05T15:00:00+10:00"},
        {"name": "old.docx", "when": "2026-10-01T15:00:00+10:00"},
    ]
    text, meta = activity_item(MONDAY, SPANS, recent, brain.register)
    assert text.startswith("Monday 5 Oct 2026 on the PC: ")
    assert "Excel 1.5 h (riverbend-costs.xlsx)" in text
    assert "VS Code" in text and "pump.py" in text and "Notepad" not in text
    assert "Sites: council.example." in text
    assert "Files opened: flot.xlsx." in text and "old.docx" not in text
    assert meta["projects"] == ["Pod"] and meta["apps"]["Excel"] == 90
    assert activity_item(date(2026, 10, 1), SPANS) is None


def test_a_days_item_is_replaced_as_the_day_goes_on(memory):
    assert write_days(memory.index, SPANS[:1], None, None, [MONDAY]) == 1
    assert write_days(memory.index, SPANS, None, None, [MONDAY, MONDAY + timedelta(1)]) == 1
    items = memory.index.with_ref(ACTIVITY, "2026-10-05")
    assert len(items) == 1 and "VS Code" in items[0].text


def test_words_for_days_look_back():
    now = datetime(2026, 10, 8, 9)  # a Thursday
    assert days_meant("yesterday", now) == [date(2026, 10, 7)]
    assert days_meant("", now) == [date(2026, 10, 8)]
    assert days_meant("last Tuesday", now) == [date(2026, 10, 6)]
    assert days_meant("Friday", now) == [date(2026, 10, 2)]  # the last one, not the next
    assert days_meant("last week", now)[0] == date(2026, 9, 28)
    assert len(days_meant("last week", now)) == 7
    assert days_meant("this week", now) == [date(2026, 10, 5) + timedelta(i) for i in range(4)]
    assert days_meant("last 3 days", now) == [
        date(2026, 10, 5),
        date(2026, 10, 6),
        date(2026, 10, 7),
    ]
    assert days_meant("whenever", now) == []


def test_recent_work_reads_the_days_back(memory):
    write_days(memory.index, SPANS, None, None, [MONDAY])
    now = datetime(2026, 10, 6, 9)
    assert "riverbend-costs.xlsx" in recent_work(memory.index, "yesterday", now)
    assert "nothing kept about" in recent_work(memory.index, "last Friday", now)
    assert "couldn't tell" in recent_work(memory.index, "whenever", now)


def test_the_brain_folds_the_pc_history_into_days_unless_told_not_to(memory):
    brain, _, _ = make(memory)
    brain.pc.spans = list(SPANS)
    assert brain.note_activity() == 1
    out = asyncio.run(brain.tools.run(ToolCall("1", "recent_work", {"when": "yesterday"})))
    assert "riverbend-costs.xlsx" in out.text and out.step == "looked back at yesterday on your PC"
    off = Settings.model_validate(
        {"routing": {"mode": "cloud-only"}, "pc": {"keep_activity": False}}
    )
    brain2, _, _ = make(memory, settings=off)
    brain2.pc.spans = list(SPANS)
    assert brain2.note_activity() == 0


def fake_git(log):
    def run(argv, **kwargs):
        folder = argv[2]
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, "main\n", "")
        log.append(folder)
        return subprocess.CompletedProcess(argv, 0, "2026-10-04T09:12:00+10:00 Fix the neck\n", "")

    return run


def make_projects(tmp_path):
    (tmp_path / "Pod" / ".git").mkdir(parents=True)
    (tmp_path / "Pod" / "README.md").write_text(
        "# Pod\n\n[![ci](x)](y)\n\nKit's first robot body: an ESP32 with a round screen.\n"
    )
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "README.txt").write_text("Loose notes, not a repo.")
    (tmp_path / "junk").mkdir()  # no git, no README: not a project
    (tmp_path / ".cache").mkdir()


def test_projects_are_folders_with_git_or_a_readme(tmp_path, memory):
    make_projects(tmp_path)
    log = []
    found = Projects(lambda: [str(tmp_path), str(tmp_path / "missing")], fake_git(log)).find()
    assert [p.name for p in found] == ["notes", "Pod"]  # by name, ignoring case
    notes, pod = found
    assert pod.purpose == "Kit's first robot body: an ESP32 with a round screen."
    assert pod.branch == "main" and pod.last_commit.endswith("Fix the neck")
    assert notes.branch == "" and notes.last_commit == ""
    assert "Code project Pod Kit's first robot body" in pod.text()


def test_projects_go_into_the_index_and_the_tools_read_them(tmp_path, memory):
    make_projects(tmp_path)
    s = Settings.model_validate(
        {
            "routing": {"mode": "cloud-only"},
            "projects": {"roots": [str(tmp_path)], "pc_roots": {str(tmp_path): "C:\\Code"}},
        }
    )
    brain, _, _ = make(memory, settings=s)
    brain.projects.run = fake_git([])
    assert brain.refresh_projects() == 2
    assert brain.refresh_projects() == 0  # once a day
    assert memory.index.count(PROJECTS) == 2
    brain.tool_context.projects = True
    listed = asyncio.run(brain.tools.run(ToolCall("1", "list_projects", {})))
    assert "- Pod: Kit's first robot body" in listed.text
    work = asyncio.run(brain.tools.run(ToolCall("1", "recent_work", {"when": "yesterday"})))
    assert "Pod: 2026-10-04T09:12:00+10:00 Fix the neck" in work.text
    missing = asyncio.run(brain.tools.run(ToolCall("1", "open_project", {"name": "zebra"})))
    assert not missing.ok


def test_a_server_path_as_the_pc_sees_it():
    mapping = {"/srv/code": "C:\\Users\\Sam\\Code", "/srv": "\\\\NAS\\srv"}
    assert pc_path("/srv/code/Kit", mapping) == "C:\\Users\\Sam\\Code\\Kit"
    assert pc_path("/srv/code", mapping) == "C:\\Users\\Sam\\Code"
    assert pc_path("/srv/other/a", mapping) == "\\\\NAS\\srv\\other\\a"
    assert pc_path("/home/x", mapping) == "/home/x"
    assert pc_path("/srv/codex", {"/srv/code": "/mnt/c"}) == "/srv/codex"
