"""The files pack (kit.tools.files): finding, reading and listing Dan's documents
from the index, and keeping a private folder's text away from the cloud."""

import asyncio

import pytest

from fakes import FakeAnthropic, collect, reply
from kit.evals import run_tool_eval
from kit.files import FILES
from kit.files.fields import fields
from kit.files.index import Files
from kit.memory import Memory
from kit.settings import Settings
from kit.tools import ToolCall
from kit.tools.files import in_folder
from kit.tools.private import MARK, lifted
from tool_helpers import Clock, make

RATES_2025 = "Richmond Council rates notice 2025-26. Assessment 123456. Amount due $1,842.60."
RATES_2024 = "Richmond Council rates notice 2024-25. Assessment 123456. Amount due $1,760.10."
LEASE = "Residential lease. Pets are allowed with the owner's written consent."


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def settings(**roots) -> Settings:
    return Settings.model_validate(
        {
            "memory": {"min_similarity": 0.3},
            "routing": {"mode": "cloud-only"},
            "files": {"roots": roots or {"finance": {"path": "/srv/finance"}}},
        }
    )


def add(memory, root, rel, text, page=1, chunk=1, private=False, kind="pdf", modified=1.7e9):
    folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
    meta = {
        "root": root,
        "rel": rel,
        "folder": folder,
        "modified": modified,
        "size": len(text),
        "page": page,
        "chunk": chunk,
        "private": private,
        "fields": fields(text),
    }
    title = rel.rsplit("/", 1)[-1]
    return memory.index.add(FILES, kind, text, title=title, ref=f"{root}:{rel}", meta=meta)


@pytest.fixture
def brain(memory, paths):
    s = settings(finance={"path": "/srv/finance"}, manuals={"path": "/srv/manuals"})
    brain, _, _ = make(memory, settings=s)
    brain.files = Files(memory.index, lambda: s, paths.state_dir)
    add(memory, "finance", "Rates/2025 rates notice.pdf", RATES_2025)
    add(memory, "finance", "Rates/2024 rates notice.pdf", RATES_2024)
    add(memory, "finance", "Home/Lease.docx", LEASE, kind="docx")
    add(memory, "manuals", "Pumps/Warman 4x3.pdf", "Pump manual. Impeller clearance.")
    add(memory, "manuals", "Pumps/Warman 4x3.pdf", "Page two: seals and gland water.", page=2)
    return brain


def run(brain, name, **args):
    return asyncio.run(brain.tools.run(ToolCall("1", name, args)))


def test_find_documents_by_words_with_one_line_per_file(brain):
    out = run(brain, "find_documents", query="rates notice")
    assert out.ok and "2025 rates notice.pdf [finance:Rates/2025 rates notice.pdf" in out.text
    assert out.text.count("Warman") == 0
    assert "Amounts: " in out.text and "$1,842.60" in out.text
    assert "Refs: Assessment 123456" in out.text
    many = run(brain, "find_documents", query="Warman pump manual seals")
    assert many.text.count("Warman 4x3.pdf [") == 1  # two pages, one line


def test_a_year_narrows_to_the_documents_about_it(brain):
    out = run(brain, "find_documents", query="rates notice", year=2024)
    assert "2024 rates notice" in out.text and "2025 rates notice" not in out.text
    none = run(brain, "find_documents", query="rates notice", year=2019)
    assert "none of these mention 2019" in none.text


def test_a_folder_or_kind_narrows_it(brain):
    assert "Lease.docx" in run(brain, "find_documents", query="lease pets", kind="docx").text
    out = run(brain, "find_documents", query="lease pets", folder="Rates")
    assert "Nothing in Dan's files in Rates" in out.text


def test_a_register_link_narrows_the_folder(brain):
    brain.register.add("Unit", "place", links=[{"system": "nas", "target": "Finance/Home"}])
    brain.current_text = "what does the Unit lease say?"
    out = run(brain, "find_documents", query="notice lease")
    assert "narrowed to Finance/Home" in out.text and "rates notice" not in out.text


def test_nothing_found_says_so(brain):
    out = run(brain, "find_documents", query="zebra")
    assert out.ok and "Nothing in Dan's files matches 'zebra'" in out.text


def test_folder_matching():
    meta = {"root": "finance", "folder": "Rates/2025"}
    assert in_folder(meta, "Rates") and in_folder(meta, "finance:Rates/2025")
    assert in_folder(meta, r"\\NAS\Finance\Rates") and not in_folder(meta, "Tax")


def test_read_document_whole_by_page_and_by_question(brain, memory):
    out = run(brain, "read_document", path="manuals:Pumps/Warman 4x3.pdf")
    assert "--- page 1 ---" in out.text and "--- page 2 ---" in out.text
    page2 = run(brain, "read_document", path="manuals:Pumps/Warman 4x3.pdf", page=2)
    assert "gland water" in page2.text and "Impeller" not in page2.text
    assert not run(brain, "read_document", path="manuals:Pumps/Warman 4x3.pdf", page=9).ok
    asked = run(brain, "read_document", path="manuals:Pumps/Warman 4x3.pdf", question="seals")
    assert "seals" in asked.text
    copied = run(brain, "read_document", path="[manuals:Pumps/Warman 4x3.pdf, page 2]")
    assert copied.ok
    assert not run(brain, "read_document", path="finance:nope.pdf").ok


def test_read_document_is_capped_at_read_words(brain, memory):
    for n in range(1, 6):
        add(memory, "finance", "Big/report.pdf", " ".join(["word"] * 600), page=n)
    out = run(brain, "read_document", path="finance:Big/report.pdf")
    assert "pieces not shown" in out.text and out.text.count("--- page") == 2


def test_list_folder(brain):
    top = run(brain, "list_folder", path="finance")
    assert "3 files indexed" in top.text and "- Rates/ (2 files)" in top.text
    rates = run(brain, "list_folder", path="finance:Rates")
    assert "2025 rates notice.pdf [finance:Rates/2025 rates notice.pdf" in rates.text
    assert run(brain, "list_folder", path="Pumps").text.count("Warman 4x3.pdf [") == 1
    assert not run(brain, "list_folder", path="Holidays").ok


def test_files_status(brain):
    out = run(brain, "files_status")
    assert "- finance: 3 files" in out.text and "- manuals: 1 file," in out.text


def test_the_tools_are_offered_only_with_a_folder(memory):
    brain, _, _ = make(
        memory, settings=Settings.model_validate({"routing": {"mode": "cloud-only"}})
    )
    collect(brain.chat("where's the lease file?"))
    assert "files" in brain.loaded_packs and not brain.tool_context.files


def test_a_private_folder_reaches_the_cloud_only_as_a_summary(memory, paths):
    s = settings(finance={"path": "/srv/finance", "private": True})
    claude = FakeAnthropic(
        answer=["", reply("It was $1,842.60, on the 2025 notice.")],
        tool_calls=[[("find_documents", {"query": "rates notice", "year": 2025})]],
    )
    brain, model, _ = make(memory, "$1,842.60, 2025 rates notice.", claude=claude, settings=s)
    brain.files = Files(memory.index, lambda: s, paths.state_dir)
    add(memory, "finance", "Rates/2025 rates notice.pdf", RATES_2025, private=True)
    collect(brain.chat("What did I pay for the rates this year?"))
    sent = str(claude.calls[1]["messages"])
    assert "Assessment 123456" not in sent and MARK in sent


def test_send_it_to_claude_lifts_the_rule_for_one_message(memory, paths):
    s = settings(finance={"path": "/srv/finance", "private": True})
    claude = FakeAnthropic(
        answer=["", reply("Pets need written consent.")],
        tool_calls=[[("read_document", {"path": "finance:Home/Lease.docx"})]],
    )
    brain, _, _ = make(memory, claude=claude, settings=s)
    brain.files = Files(memory.index, lambda: s, paths.state_dir)
    add(memory, "finance", "Home/Lease.docx", LEASE, private=True, kind="docx")
    collect(brain.chat("Send it to Claude: what does the lease say about pets?"))
    assert "written consent" in str(claude.calls[1]["messages"])


def test_the_lift_phrases():
    assert lifted("send it to Claude") and lifted("You can use the cloud for this")
    assert not lifted("send it to Mum") and not lifted("what's in the cloud backup?")


def test_the_files_cases_pass_offline(brain):
    cases = brain.tools.packs["files"].cases
    report = asyncio.run(run_tool_eval(brain, cases))
    assert report.passed, [r.why for r in report.results if not r.passed]
