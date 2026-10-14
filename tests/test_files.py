"""Dan's files in the index (kit.files): walking the roots, reading each kind, the
fields pulled out, syncing as files come and go, the roots as settings, the routes
and ``kit files``."""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kit.checks import Status, check_files
from kit.cli import cmd_files, file_place
from kit.credentials import api_token
from kit.files import FILES, Root, RootError, add_root, change_root, remove_root, roots_from
from kit.files.extract import Page, Unavailable, extract
from kit.files.fields import fields
from kit.files.index import Files, chunks
from kit.files.walk import Found, Walker, changes
from kit.memory import Memory
from kit.server import create_app
from kit.settings import Settings
from kit.settings_store import SettingsStore
from tool_helpers import Clock, make

NOTICE = """Richmond Council
Rates notice 2025-26

Assessment 123456
Issued 14/08/2025

Amount due $1,842.60 by 30 September 2025.
ABN 12 345 678 901"""


def pdf_bytes(lines: list[str]) -> bytes:
    """A one-page PDF with ``lines`` of text, written by hand so no PDF writer is
    needed beyond pypdf for reading it back."""
    text = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(
        "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '"
        for ln in lines
    )
    stream = text.encode() + b" ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


@pytest.fixture
def finance(tmp_path):
    folder = tmp_path / "Finance"
    (folder / "Rates").mkdir(parents=True)
    (folder / "Rates" / "notice.txt").write_text(NOTICE, encoding="utf-8")
    (folder / "todo.md").write_text("# Things\n\nRenew the car rego.", encoding="utf-8")
    return folder


class Settable:
    """Settings that a test can change between syncs."""

    def __init__(self, settings: Settings) -> None:
        self.value = settings

    def __call__(self) -> Settings:
        return self.value


def with_roots(**roots) -> Settings:
    return Settings.model_validate({"files": {"roots": roots}})


def make_files(memory, paths, settings, **kw) -> Files:
    clock = kw.pop("clock", lambda: datetime(2026, 10, 14, 9, 0))
    return Files(memory.index, settings, paths.state_dir, clock=clock, **kw)


# Walking


def test_the_walker_skips_names_types_big_files_and_links(tmp_path):
    root = tmp_path / "Docs"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "x.txt").write_text("no")
    (root / "@eaDir" / "deep").mkdir(parents=True)
    (root / "@eaDir" / "deep" / "y.txt").write_text("no")
    (root / "~$draft.docx").write_text("no")
    (root / "photo.jpg").write_text("no")
    (root / "big.txt").write_text("x" * (1024 * 1024 + 1))
    (root / "keep.txt").write_text("yes")
    (root / "Sub").mkdir()
    (root / "Sub" / "also.CSV").write_text("a,b")
    if sys.platform != "win32":
        os.symlink(root / "keep.txt", root / "link.txt")
    walker = Walker([Root("docs", root, max_mb=1)], Settings().files.skip)
    found = list(walker.walk())
    assert [f.rel for f in found] == ["Sub/also.CSV", "keep.txt"]
    assert found[0].kind == "csv" and found[0].ref == "docs:Sub/also.CSV"
    assert walker.errors == []


def test_a_folder_that_cant_be_read_is_skipped_not_fatal(tmp_path):
    root = tmp_path / "Docs"
    (root / "Locked").mkdir(parents=True)
    (root / "fine.txt").write_text("yes")
    real = os.scandir

    def scandir(folder):
        if Path(folder).name == "Locked":
            raise PermissionError("no entry")
        return real(folder)

    walker = Walker([Root("docs", root)], [], scandir=scandir)
    assert [f.rel for f in walker.walk()] == ["fine.txt"]
    assert walker.errors and walker.errors[0][0] == "docs:Locked"


def test_changes_new_changed_by_size_or_time_and_gone():
    def f(rel, modified=1.0, size=10):
        return Found("r", Path(rel), rel, size, modified, "txt")

    known = {"r:same": (1.0, 10), "r:bigger": (1.0, 10), "r:newer": (1.0, 10), "r:gone": (1, 1)}
    out = changes([f("same"), f("bigger", size=11), f("newer", modified=2.0), f("new")], known)
    assert [x.rel for x in out.new] == ["new"]
    assert sorted(x.rel for x in out.changed) == ["bigger", "newer"]
    assert out.gone == ["r:gone"]


# Reading


def test_text_files_are_read_whole(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes("caf\xe9 au lait".encode("latin-1"))
    pages = extract(p, "md")
    assert len(pages) == 1 and "au lait" in pages[0].text


def test_a_pdf_page_by_page(tmp_path):
    pytest.importorskip("pypdf")
    p = tmp_path / "notice.pdf"
    p.write_bytes(pdf_bytes(["Rates notice", "Amount due $1,842.60"]))
    pages = extract(p, "pdf")
    assert len(pages) == 1 and "$1,842.60" in pages[0].text


def test_word_paragraphs_and_tables(tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Insurance renewal")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Premium"
    table.rows[0].cells[1].text = "$912.00"
    p = tmp_path / "policy.docx"
    doc.save(p)
    text = extract(p, "docx")[0].text
    assert "Insurance renewal" in text and "Premium\t$912.00" in text


def test_a_sheet_per_page_with_its_name_and_a_row_cap(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "Fuel"
    for n in range(10):
        book.active.append([f"2025-0{n % 9 + 1}-01", 60 + n])
    book.create_sheet("Notes").append(["Nothing much"])
    p = tmp_path / "car.xlsx"
    book.save(p)
    pages = extract(p, "xlsx", max_rows=3)
    assert [(pg.number, pg.title) for pg in pages] == [(1, "Fuel"), (2, "Notes")]
    assert len(pages[0].text.splitlines()) == 3


def test_slides_a_page_each(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    for title in ("Plant shutdown", "Lessons"):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
    p = tmp_path / "talk.pptx"
    deck.save(p)
    pages = extract(p, "pptx")
    assert [pg.text for pg in pages] == ["Plant shutdown", "Lessons"]


def test_a_missing_library_is_unavailable(tmp_path, monkeypatch):
    import kit.files.extract as ex

    monkeypatch.setitem(ex.PACKAGES, "pdf", ("no_such_pdf_library", "pypdf"))
    with pytest.raises(Unavailable, match="pypdf"):
        extract(tmp_path / "x.pdf", "pdf")


# Fields and pieces


def test_fields_from_a_rates_notice():
    out = fields(NOTICE + "\nFY2024-25 summary", ["Richmond Council", "Hilux"])
    assert {2024, 2025} <= set(out["years"])
    assert out["amounts"] == [1842.60]
    assert "Amount due $1,842.60" in out["amount_lines"][0]
    assert "2025-08-14" in out["dates"]
    assert out["abn"] == ["12 345 678 901"]
    assert "Assessment 123456" in out["references"]
    assert out["names"] == ["Richmond Council"]


def test_fields_leave_out_what_isnt_there():
    assert fields("just words") == {}


def test_pieces_cut_at_paragraphs_and_long_ones_by_words():
    text = "\n\n".join(["one two three"] * 4 + [" ".join(["w"] * 10)])
    out = chunks(text, 6)
    assert out[0] == "one two three\n\none two three"
    assert out[-1].split() == ["w"] * 4 and len(out) == 4
    assert chunks("  ", 6) == []
    assert chunks("a\nb\nc", 2) == ["a\n\nb", "c"]


# Syncing


def test_a_sync_indexes_then_finds_nothing_new_then_follows_a_change(memory, paths, finance):
    settings = Settable(with_roots(finance={"path": str(finance)}))
    files = make_files(memory, paths, settings, names=lambda: ["Richmond Council"])
    report = files.sync()
    assert (report.indexed, report.unchanged, report.removed) == (2, 0, 0)
    items = memory.index.items(FILES)
    notice = next(i for i in items if i.ref == "finance:Rates/notice.txt")
    assert notice.title == "notice.txt" and notice.kind == "txt"
    assert notice.meta["folder"] == "Rates" and notice.meta["page"] == 1
    assert notice.meta["fields"]["amounts"] == [1842.60]
    assert notice.meta["fields"]["names"] == ["Richmond Council"]
    assert notice.meta["private"] is False

    assert files.sync().line() == "0 indexed, 2 unchanged, 0 removed"

    p = finance / "Rates" / "notice.txt"
    p.write_text(NOTICE.replace("1,842.60", "1,901.15") + "\nPaid.", encoding="utf-8")
    assert files.sync().indexed == 1
    texts = [i.text for i in memory.index.items(FILES) if i.ref == "finance:Rates/notice.txt"]
    assert len(texts) == 1 and "1,901.15" in texts[0]

    (finance / "todo.md").unlink()
    assert files.sync().removed == 1
    assert {i.ref for i in memory.index.items(FILES)} == {"finance:Rates/notice.txt"}


def test_a_full_sync_reads_everything_again(memory, paths, finance):
    files = make_files(memory, paths, Settable(with_roots(finance={"path": str(finance)})))
    files.sync()
    assert files.sync(full=True).indexed == 2
    assert len(memory.index.items(FILES)) == 2


def test_a_file_that_cant_be_read_is_tried_again_only_once_it_changes(memory, paths, finance):
    tries = []

    def broken(path, kind, **kw):
        tries.append(path.name)
        if path.name == "todo.md":
            raise ValueError("damaged")
        return extract(path, kind, **kw)

    files = make_files(
        memory, paths, Settable(with_roots(finance={"path": str(finance)})), extract=broken
    )
    report = files.sync()
    assert report.failed == [("finance:todo.md", "ValueError: damaged")]
    tries.clear()
    files.sync()
    assert tries == []
    (finance / "todo.md").write_text("changed", encoding="utf-8")
    files.sync()
    assert tries == ["todo.md"]
    assert files.status()["finance"]["unreadable"] == ["finance:todo.md"]


def test_a_missing_library_is_recorded_and_the_rest_carry_on(memory, paths, finance):
    def no_pdf(path, kind, **kw):
        raise Unavailable("txt", "pypdf")

    files = make_files(
        memory, paths, Settable(with_roots(finance={"path": str(finance)})), extract=no_pdf
    )
    report = files.sync()
    assert report.indexed == 0 and len(report.failed) == 2
    assert "pypdf" in report.failed[0][1]


def test_a_scan_with_no_text_keeps_its_name_findable(memory, paths, finance):
    files = make_files(
        memory,
        paths,
        Settable(with_roots(finance={"path": str(finance)})),
        extract=lambda path, kind, **kw: [Page(1, "")],
    )
    files.sync()
    item = next(i for i in memory.index.items(FILES) if i.ref == "finance:todo.md")
    assert item.text == "todo.md (no text in it)" and item.meta["no_text"]


def test_pages_and_sheets_give_titles_and_page_numbers(memory, paths, finance):
    def two_pages(path, kind, **kw):
        return [Page(1, "first"), Page(2, "second")]

    def sheets(path, kind, **kw):
        return [Page(1, "a\tb", "Fuel")]

    files = make_files(
        memory, paths, Settable(with_roots(finance={"path": str(finance)})), extract=two_pages
    )
    files.sync(only="finance")
    titles = sorted(i.title for i in memory.index.items(FILES) if i.ref == "finance:todo.md")
    assert titles == ["todo.md (page 1)", "todo.md (page 2)"]
    page2 = next(i for i in memory.index.items(FILES) if i.title == "todo.md (page 2)")
    assert file_place(page2) == "finance: todo.md, page 2"
    files.extract = sheets
    files.sync(full=True)
    assert any(i.title == "todo.md > Fuel" for i in memory.index.items(FILES))


def test_an_unreachable_root_changes_nothing(memory, paths, finance, tmp_path):
    settings = Settable(with_roots(finance={"path": str(finance)}))
    files = make_files(memory, paths, settings)
    files.sync()
    settings.value = with_roots(finance={"path": str(tmp_path / "unplugged")})
    report = files.sync()
    assert report.removed == 0 and "isn't reachable" in report.failed[0][1]
    assert len(memory.index.items(FILES)) == 2
    assert files.status()["finance"]["reachable"] is False


def test_private_and_removed_roots_follow_the_settings(memory, paths, finance, tmp_path):
    other = tmp_path / "Manuals"
    other.mkdir()
    (other / "pump.txt").write_text("Impeller clearance 0.5 mm", encoding="utf-8")
    settings = Settable(with_roots(finance={"path": str(finance)}, manuals={"path": str(other)}))
    files = make_files(memory, paths, settings)
    files.sync()
    settings.value = with_roots(finance={"path": str(finance), "private": True})
    report = files.sync()
    assert report.removed == 1  # manuals left the settings
    assert {i.meta["root"] for i in memory.index.items(FILES)} == {"finance"}
    assert all(i.meta["private"] for i in memory.index.items(FILES))
    assert "manuals" not in files._read_json("runs.json")


def test_status_per_root(memory, paths, finance):
    files = make_files(memory, paths, Settable(with_roots(finance={"path": str(finance)})))
    files.sync()
    s = files.status()["finance"]
    assert (s["files"], s["pieces"], s["reachable"]) == (2, 2, True)
    assert s["last_run"] == {
        "at": "2026-10-14T09:00:00",
        "result": "2 indexed, 0 unchanged, 0 removed",
    }


def test_files_come_into_chat_only_through_the_files_pack():
    from kit.tools import core

    source = Path(core.__file__).read_text(encoding="utf-8")
    assert "FILES" not in source  # the files pack marks private roots; recall doesn't


# Roots as settings


def test_roots_are_added_changed_and_removed_in_the_settings(paths, finance):
    paths.ensure()
    store = SettingsStore(paths)
    add_root(store, "finance", str(finance), private=True)
    assert roots_from(store.current()) == [Root("finance", finance, private=True)]
    with pytest.raises(RootError, match="already"):
        add_root(store, "finance", str(finance))
    with pytest.raises(RootError, match="name"):
        add_root(store, "my files", str(finance))
    with pytest.raises(RootError, match="isn't a folder"):
        add_root(store, "gone", str(finance / "nope"))
    change_root(store, "finance", private=False, max_mb=10)
    root = store.current().files.roots["finance"]
    assert (root.private, root.max_mb) == (False, 10)
    remove_root(store, "finance")
    assert store.current().files.roots == {}
    with pytest.raises(RootError, match="no root"):
        remove_root(store, "finance")


def test_kit_check_lists_the_libraries_and_each_root(finance, tmp_path):
    assert check_files(Settings())[0].status is Status.SKIP
    s = with_roots(finance={"path": str(finance)}, nas={"path": str(tmp_path / "x")})
    out = check_files(
        s, libraries=lambda: {"pypdf": True, "openpyxl": False}, write=lambda f: OSError()
    )
    assert out[0].status is Status.WARN and "openpyxl" in out[0].detail
    assert out[1].status is Status.PASS and "read-only" in out[1].detail
    assert out[2].status is Status.FAIL
    writable = check_files(s, libraries=lambda: {}, write=lambda f: None)
    assert writable[1].status is Status.WARN


# The routes and kit files


@pytest.fixture
def app(paths, memory):
    paths.ensure()
    brain, _, _ = make(memory)
    app = create_app(SettingsStore(paths), memory, brain, api_token(paths), summarise_every_s=None)
    return app


@pytest.fixture
def auth(paths):
    return {"Authorization": f"Bearer {api_token(paths)}"}


def test_the_routes_add_change_sync_and_remove_a_root(app, auth, finance, memory):
    with TestClient(app) as client:
        assert client.get("/api/files").status_code == 401
        bad = client.post(
            "/api/files/roots", json={"name": "x", "path": str(finance / "no")}, headers=auth
        )
        assert bad.status_code == 400 and "isn't a folder" in bad.json()["detail"]
        out = client.post(
            "/api/files/roots", json={"name": "finance", "path": str(finance)}, headers=auth
        ).json()
        assert out["roots"]["finance"]["path"] == str(finance)
        for _ in range(100):  # the first read runs in the background
            if not client.get("/api/files", headers=auth).json()["running"]:
                break
            time.sleep(0.05)
        assert client.get("/api/files", headers=auth).json()["roots"]["finance"]["files"] == 2
        out = client.patch("/api/files/roots/finance", json={"private": True}, headers=auth).json()
        assert out["roots"]["finance"]["private"]
        assert all(i.meta["private"] for i in memory.index.items(FILES))
        assert (
            client.post("/api/files/sync", json={"root": "nope"}, headers=auth).status_code == 404
        )
        out = client.delete("/api/files/roots/finance", headers=auth).json()
        assert out["dropped"] == 2 and out["roots"] == {}
        assert memory.index.items(FILES) == []


def test_the_memory_page_search_finds_files(app, auth, finance, memory, paths):
    files = make_files(memory, paths, Settable(with_roots(finance={"path": str(finance)})))
    files.sync()
    with TestClient(app) as client:
        hits = client.get("/api/memory/search", params={"q": "rates notice"}, headers=auth).json()
    hit = next(h for h in hits["hits"] if h["source"] == FILES)
    assert hit["meta"]["rel"] == "Rates/notice.txt"


def files_args(action, **kw):
    base = {"action": action, "name": None, "path": None, "private": False, "ocr": False}
    return argparse.Namespace(**{**base, **kw})


def test_kit_files_add_status_private_remove(paths, finance, capsys):
    paths.ensure()
    assert cmd_files(paths, files_args("status")) == 0
    assert "no folders yet" in capsys.readouterr().out
    assert cmd_files(paths, files_args("add", name="finance", path=str(finance))) == 0
    assert "added finance" in capsys.readouterr().out
    assert cmd_files(paths, files_args("add", name="finance", path=str(finance))) == 1
    capsys.readouterr()
    memory = Memory(paths.state_dir / "memory.db", Clock())
    try:
        make_files(memory, paths, SettingsStore(paths).current).sync()
    finally:
        memory.close()
    assert cmd_files(paths, files_args("status")) == 0
    out = capsys.readouterr().out
    assert f"finance: {finance}" in out and "2 files, 2 pieces" in out
    assert cmd_files(paths, files_args("private", name="finance", state="on")) == 0
    assert "private (2 pieces changed)" in capsys.readouterr().out
    assert cmd_files(paths, files_args("remove", name="finance")) == 0
    assert "2 pieces left the index" in capsys.readouterr().out
