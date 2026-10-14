"""The ``files`` pack: asking about Dan's documents mid-answer. Find documents in
the files index (kit.files) with a year, folder or kind to narrow it, read the
pieces of one that answer a question, list a folder, and say what's indexed. Every
tool reads the index, never the folders themselves, so they're quick and work while
the NAS sleeps. A file from a private root comes back marked private, so a cloud
model only gets the local model's short answer from it (kit.tools.private).
See docs/2 How Kit Works/Your Files.md."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from kit.files import FILES
from kit.tools import EvalCase, Pack, Tool, ToolResult

if TYPE_CHECKING:
    from kit.brain import Brain
    from kit.knowledge import Item

SNIPPET = 200
LIST_MAX = 40
LINK_SYSTEMS = ("nas", "code")  # register links that name a folder of Dan's


def _segments(path: str) -> list[str]:
    return [s for s in re.split(r"[\\/:]+", path.lower()) if s]


def in_folder(meta: dict, folder: str) -> bool:
    """Whether a piece's file sits under ``folder``: a run of folder names (``Rates``,
    ``Finance/Rates``, ``finance:Rates``) found in its root and folders, or failing
    that the folder's last name. Slashes either way, any case."""
    want = _segments(folder)
    if not want:
        return True
    have = _segments(meta.get("root", "")) + _segments(meta.get("folder", ""))
    n = len(want)
    if any(have[i : i + n] == want for i in range(len(have) - n + 1)):
        return True
    return want[-1] in have


def has_year(item: Item, year: int) -> bool:
    years = item.meta.get("fields", {}).get("years", [])
    return year in years or str(year) in item.meta.get("rel", "")


def _year(value) -> int | None:
    try:
        year = int(str(value).strip()[:4])
    except (TypeError, ValueError):
        return None
    return year if 1900 < year < 2100 else None


def place(meta: dict) -> str:
    """Where a piece is: ``root:path``, the path read_document and list_folder take."""
    return f"{meta.get('root', '')}:{meta.get('rel', '')}"


def _when(meta: dict) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(meta.get("modified"))).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def file_line(item: Item) -> str:
    m = item.meta
    page = f", page {m['page']}" if m.get("page", 1) > 1 else ""
    name = m.get("rel", "").rsplit("/", 1)[-1] or item.title
    text = " ".join(item.text.split())
    if len(text) > SNIPPET:
        text = text[:SNIPPET].rsplit(" ", 1)[0] + "..."
    line = f"- {name} [{place(m)}{page}, changed {_when(m)}]: {text}"
    fields = m.get("fields", {})
    if fields.get("amount_lines"):
        line += " | Amounts: " + "; ".join(fields["amount_lines"][:4])
    if fields.get("references"):
        line += " | Refs: " + ", ".join(fields["references"][:3])
    return line


def files_pack(brain: Brain) -> Pack:
    """The files pack for ``brain``, offered once there's a root in the settings."""

    def owner() -> str:
        return brain.settings().persona.owner

    def index():
        return brain.memory.index

    def linked_folders() -> list[str]:
        """Folders the register links to the things named in this message."""
        return [
            link.target
            for thing in brain.register.mentioned_in(brain.current_text)
            for link in thing.links
            if link.system in LINK_SYSTEMS and link.target
        ]

    async def find_documents(args: dict) -> ToolResult:
        query = str(args.get("query", "")).strip()
        year = _year(args.get("year"))
        folder = str(args.get("folder", "") or "").strip()
        kind = str(args.get("kind", "") or "").strip().lower().lstrip(".")
        limit = max(1, min(int(args.get("limit") or 8), 20))
        hits = [h.item for h in await brain.recall.search(query, [FILES], limit * 6)]
        notes = []
        if kind:
            hits = [i for i in hits if i.kind == kind or (kind == "xls" and i.kind == "xlsx")]
        if folder:
            hits = [i for i in hits if in_folder(i.meta, folder)]
        else:
            for target in linked_folders():
                narrowed = [i for i in hits if in_folder(i.meta, target)]
                if narrowed:
                    hits = narrowed
                    notes.append(f"(narrowed to {target}, where the register says it lives)")
                    break
        if year is not None:
            dated = [i for i in hits if has_year(i, year)]
            if dated:
                hits = dated
            elif hits:
                notes.append(f"(none of these mention {year}; the closest matches are below)")
        best: dict[str, Item] = {}
        for item in hits:  # best piece of each file, in rank order
            best.setdefault(item.ref or "", item)
        found = list(best.values())[:limit]
        step = f"looked through your files for '{query}'"
        event = {"type": "found_documents", "query": query, "found": len(found)}
        if not found:
            where = f" in {folder}" if folder else ""
            return ToolResult(
                f"Nothing in {owner()}'s files{where} matches '{query}'"
                + (f" for {year}" if year else "")
                + ". Say so; they could try other words or another year.",
                event=event,
                step=step,
            )
        lines = [f"{owner()}'s files matching '{query}', best first:", *notes]
        lines += [file_line(i) for i in found]
        lines.append(
            "Each [place] is the path for read_document. Name the file you answer from. "
            "You can't open files on the PC yet."
        )
        private = any(i.meta.get("private") for i in found)
        return ToolResult("\n".join(lines), event=event, step=step, private=private)

    async def read_document(args: dict) -> ToolResult:
        path = str(args.get("path", "")).strip().strip("[]")
        path = re.sub(r",\s*page \d+.*$", "", path)  # a place copied with its page
        question = str(args.get("question", "") or "").strip()
        page = args.get("page")
        pieces = index().with_ref(FILES, path)
        if not pieces:
            return ToolResult(
                f"There's no file '{path}' in the index. Use find_documents to find it first.",
                ok=False,
            )
        cap = brain.settings().files.read_words
        if page not in (None, ""):
            try:
                wanted = int(page)
            except (TypeError, ValueError):
                wanted = 1
            chosen = [p for p in pieces if p.meta.get("page") == wanted]
            if not chosen:
                pages = max(p.meta.get("page", 1) for p in pieces)
                return ToolResult(f"{path} has no page {wanted}; it has {pages}.", ok=False)
        elif question and len(pieces) > 1:
            chosen = await _best_pieces(question, pieces)
        else:
            chosen = list(pieces)
        kept, words = [], 0
        for piece in chosen:
            n = len(piece.text.split())
            if kept and words + n > cap:
                break
            kept.append(piece)
            words += n
        kept.sort(key=lambda p: (p.meta.get("page", 1), p.meta.get("chunk", 1)))
        pages = max(p.meta.get("page", 1) for p in pieces)
        lines = [f"From {path} ({pages} page{'s' if pages != 1 else ''}, {_when(pieces[0].meta)}):"]
        last = None
        for piece in kept:
            if pages > 1 and piece.meta.get("page") != last:
                last = piece.meta.get("page")
                lines.append(f"--- page {last} ---")
            lines.append(piece.text.strip())
        if len(kept) < len(pieces):
            lines.append(
                f"(only the most relevant part; {len(pieces) - len(kept)} pieces not shown)"
            )
        name = path.rsplit("/", 1)[-1]
        return ToolResult(
            "\n".join(lines),
            event={"type": "reading_document", "path": path},
            step=f"read {name}",
            private=bool(pieces[0].meta.get("private")),
        )

    async def _best_pieces(question: str, pieces: list[Item]) -> list[Item]:
        """The pieces in the order they answer ``question``: by meaning when the
        embedder is up, else by the words they share with it."""
        scores: dict[int, float] = {}
        vec = await brain.recall.query_vector(question)
        if vec is not None and brain.recall.embedder is not None:
            sims = index().similarities(vec, brain.recall.embedder.model, [FILES])
            scores = {p.id: sims[p.id] for p in pieces if p.id in sims}
        if not scores:
            words = set(_segments(re.sub(r"\W+", " ", question)))
            scores = {p.id: len(words & set(p.text.lower().split())) for p in pieces}
        return sorted(pieces, key=lambda p: -scores.get(p.id, 0.0))

    async def list_folder(args: dict) -> ToolResult:
        path = str(args.get("path", "")).strip().strip("/\\")
        roots = set(brain.settings().files.roots)
        root, rel = "", path
        if ":" in path:
            root, rel = path.split(":", 1)
        else:
            first = _segments(path)[:1]
            if first and first[0] in {r.lower() for r in roots}:
                root = next(r for r in roots if r.lower() == first[0])
                rel = path[len(root) :]
        rel = "/".join(_segments(rel)) if rel else ""
        docs = [
            (ref, meta)
            for ref, meta in index().documents(FILES)
            if (not root or meta.get("root") == root)
            and (not rel or in_folder({"folder": meta.get("folder", "")}, rel))
        ]
        if not docs:
            return ToolResult(
                f"Nothing indexed under '{path}'. The folders are: {', '.join(sorted(roots))}.",
                ok=False,
            )
        here, below = [], {}
        for ref, meta in docs:
            folder = meta.get("folder", "")
            segs = _segments(folder)
            depth = _match_end(segs, _segments(rel)) if rel else 0
            if depth == len(segs):
                here.append((ref, meta))
            else:
                sub = folder.split("/")[depth]
                below[sub] = below.get(sub, 0) + 1
        lines = [f"In {path or 'your folders'}: {len(docs)} files indexed."]
        for sub, count in sorted(below.items())[:LIST_MAX]:
            lines.append(f"- {sub}/ ({count} file{'s' if count != 1 else ''})")
        for ref, meta in sorted(here, key=lambda d: -float(d[1].get("modified") or 0))[:LIST_MAX]:
            lines.append(
                f"- {meta.get('rel', '').rsplit('/', 1)[-1]} [{ref}, changed {_when(meta)}]"
            )
        if len(here) > LIST_MAX:
            lines.append(f"(and {len(here) - LIST_MAX} more files, newest shown)")
        return ToolResult(
            "\n".join(lines),
            event={"type": "listed_folder", "path": path},
            step=f"looked in {path or 'your folders'}",
        )

    async def files_status(args: dict) -> ToolResult:
        if brain.files is None:
            return ToolResult("Your files aren't set up on this Kit.", ok=False)
        lines = [f"The folders of {owner()}'s you've read:"]
        for name, r in brain.files.status().items():
            there = "" if r["reachable"] else ", can't be reached just now"
            private = ", private" if r["private"] else ""
            last = (
                f", last looked {r['last_run']['at'][:16]}" if r["last_run"] else ", not read yet"
            )
            count = f"{r['files']} file" + ("" if r["files"] == 1 else "s")
            lines.append(f"- {name}: {count}{private}{there}{last}")
        return ToolResult("\n".join(lines), step="checked which folders you've read")

    def offered() -> bool:
        return brain.tool_context.files

    return Pack(
        "files",
        "the owner's documents in the folders they chose: find, read, list",
        words=[
            "document",
            "documents",
            "doc",
            "file",
            "files",
            "folder",
            "folders",
            "invoice",
            "invoices",
            "receipt",
            "receipts",
            "statement",
            "notice",
            "rates",
            "tax",
            "pdf",
            "spreadsheet",
            "contract",
            "lease",
            "manual",
            "bill",
            "insurance",
            "policy",
            "warranty",
        ],
        questions=[
            "What did I pay for property tax last year?",
            "Where's the lease for the unit?",
            "What's in the Riverbend folder?",
            "Find the pump manual",
            "How much was the last electricity bill?",
            "When does the car insurance renew?",
            "Have you got my documents?",
            "Show me the quotes for the kitchen",
            "What does the contract say about notice?",
            "Bring up everything on the project",
        ],
        systems=list(LINK_SYSTEMS),
        cases=[
            EvalCase(
                "What did I pay for the council rates last year?",
                "find_documents",
                {"query": "rates"},
            ),
            EvalCase("Find the pump manual", "find_documents", {"query": "pump"}),
            EvalCase("What's in the Finance folder?", "list_folder", {"path": "Finance"}),
            EvalCase("Have you read my files yet?", "files_status"),
        ],
        tools=[
            Tool(
                "find_documents",
                "Search the owner's documents (PDFs, Word files, spreadsheets, slides, text "
                "in the folders they chose) by what's in them. Use it for bills, notices, "
                "statements, receipts, manuals, contracts, quotes and anything 'in my "
                "files'. Put the words likely to be in the document (not a sentence); give "
                "year for a year they mean ('last year' is the year before today's), folder "
                "for a folder they name, kind (pdf, docx, xlsx, pptx) if they say one. "
                "Each result has a place to pass to read_document.",
                find_documents,
                {
                    "query": {"type": "string", "description": "Words to look for."},
                    "year": {"type": "integer", "description": "A year the document is about."},
                    "folder": {"type": "string", "description": "A folder to look in."},
                    "kind": {"type": "string", "description": "pdf, docx, xlsx, pptx, txt."},
                    "limit": {"type": "integer", "description": "Most files to list (8)."},
                },
                ["query"],
                examples=[
                    {"query": "council rates notice", "year": 2025},
                    {"query": "pump manual", "kind": "pdf"},
                ],
                offered=offered,
                speak="You're about to look through {owner}'s files for '{query}'. Say so in "
                "a few words.",
            ),
            Tool(
                "read_document",
                "Read one document found by find_documents: the parts that answer the "
                "question, or one page. Use it when the snippet isn't enough to answer.",
                read_document,
                {
                    "path": {
                        "type": "string",
                        "description": "A place from find_documents, e.g. finance:Rates/a.pdf.",
                    },
                    "question": {"type": "string", "description": "What you want from it."},
                    "page": {"type": "integer", "description": "One page to read."},
                },
                ["path"],
                examples=[{"path": "finance:Rates/2025 notice.pdf", "question": "amount due"}],
                offered=offered,
                speak="You're about to read one of {owner}'s documents. Say so in a few words.",
            ),
            Tool(
                "list_folder",
                "List what's in one of the owner's folders (as indexed): its sub-folders "
                "and newest files. Use it for 'what's in the X folder' or to see a project's "
                "documents together.",
                list_folder,
                {
                    "path": {
                        "type": "string",
                        "description": "A folder name or place, like Finance or finance:Rates.",
                    }
                },
                ["path"],
                examples=[{"path": "finance:Rates"}],
                offered=offered,
                speak="You're about to look in {owner}'s '{path}' folder. Say so in a few words.",
            ),
            Tool(
                "files_status",
                "Which of the owner's folders you've read, how many files each, and when "
                "you last looked. Use it for 'have you got my documents?'.",
                files_status,
                offered=offered,
            ),
        ],
    )


def _match_end(have: list[str], want: list[str]) -> int:
    """Where ``want`` ends inside ``have`` (a folder's segments), so what's left is
    below it; the whole length when it isn't there."""
    n = len(want)
    for i in range(len(have) - n + 1):
        if have[i : i + n] == want:
            return i + n
    if want and want[-1] in have:
        return have.index(want[-1]) + 1
    return len(have)
