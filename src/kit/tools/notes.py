"""The ``notes`` pack: Dan's Obsidian vault, properly. Find notes, list open tasks,
add to a note under a heading, change a line, tick a task, start a note, open one
in Obsidian on the PC, and undo the last change.

Kit still writes only when told to or after a yes (Dan, 2026-10-07): adding to a
note or starting one runs straight away when Dan's message plainly asked for it
(``asks_for_note``) and asks first otherwise; changing a line, ticking a task and
undoing always ask, showing the change. A note edited in Obsidian between the ask
and the yes is read again, never written over (kit.notes_edit). The pack's
context lines say how the vault is laid out (``Notes.shape``). Reading one note is
the core pack's ``read_note``. See docs/2 How Kit Works/Notes on the NAS.md."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from kit.notes import NOTES, NoteError, asks_for_note, shape_lines
from kit.notes_edit import Append, Change, Edit, New, NoteChanged, Tick, last_undo, undo
from kit.notes_tasks import TASKS, due_window
from kit.prompt import recall_results
from kit.tools import EvalCase, Pack, Tool, ToolResult

if TYPE_CHECKING:
    from kit.brain import Brain
    from kit.settings import Settings

FIND_K = 8
TASKS_MAX = 25


def undo_dir(brain: Brain) -> Path:
    """Where the notes as they were before Kit's changes are kept (state/notes/undo)."""
    return brain.memory.path.parent / "notes" / "undo"


def notes_pack(brain: Brain) -> Pack:
    # The change each held call was shown with: a yes applies it only if the note
    # still has the same modified time (kit.notes_edit.NoteChanged otherwise).
    shown: dict[str, float | None] = {}

    def owner() -> str:
        return brain.settings().persona.owner

    def nas():
        return brain.settings().nas

    def key(name: str, args: dict) -> str:
        return name + json.dumps(args, sort_keys=True)

    def ctx():
        return brain.tool_context

    def change_for(name: str, args: dict) -> Change:
        note = str(args.get("note", "")).strip()
        if name == "append_note":
            return Append(
                note, text=str(args.get("text", "")), section=str(args.get("section") or "")
            )
        if name == "edit_note":
            return Edit(note, find=str(args.get("find", "")), replace=str(args.get("replace", "")))
        if name == "tick_task":
            task = str(args.get("task", "")).strip()
            return Tick(note or task_note(task), task=task)
        return New(
            "",
            title=str(args.get("title", "")),
            folder=str(args.get("folder") or ""),
            template=str(args.get("template") or ""),
            text=str(args.get("text") or ""),
            templates_folder=brain.notes.shape(nas(), brain.settings().notes).templates or "",
        )

    def task_note(task: str) -> str:
        """The one note holding an open task like ``task``, when no note was named."""
        want = task.lower()
        notes = {
            t.meta.get("note")
            for t in brain.memory.index.items(TASKS, limit=100_000)
            if want and want in t.title.lower()
        }
        if len(notes) == 1:
            return notes.pop()
        if not notes:
            raise NoteError(f"there's no open task like '{task}' in your notes")
        raise NoteError(f"'{task}' is in several notes: {', '.join(sorted(notes)[:6])}; which?")

    def preview_for(name: str):
        def preview(args: dict) -> str:
            change = change_for(name, args).build(brain.notes, nas())
            shown[key(name, args)] = change.mtime
            return change.preview()

        return preview

    def run_change(name: str):
        async def run(args: dict) -> ToolResult:
            settings = brain.settings()
            try:
                change = await asyncio.to_thread(
                    change_for(name, args).build, brain.notes, settings.nas
                )
                expected = shown.pop(key(name, args), change.mtime)
                if expected != change.mtime:
                    raise NoteChanged(f"{change.note} changed since I showed you the change")
                applied = await asyncio.to_thread(
                    change.apply,
                    settings.nas,
                    undo_dir(brain),
                    brain.memory.clock,
                    settings.notes.undo_keep,
                )
            except NoteChanged as e:
                body = ""
                try:
                    _, body = brain.notes.read(settings.nas, change.note)
                except NoteError:
                    pass
                return ToolResult(
                    f"Not done: {e}. Here's the note as it is now; ask {owner()} again "
                    f"with the change made against this:\n{body}",
                    ok=False,
                )
            except NoteError as e:
                return ToolResult(f"Not done: {e}.", ok=False)
            await asyncio.to_thread(brain.notes.refresh, settings.nas, applied.path)
            undo_line = " It can be undone." if applied.undo_file else ""
            return ToolResult(
                f"Done: {change.what} ({applied.shown}).{undo_line}",
                event={"type": "note_changed", "note": applied.shown, "change": change.what},
                step=change.what,
            )

        return run

    def asked(args: dict, settings: Settings) -> bool:
        """A note Dan's message didn't plainly ask for is offered first."""
        return not asks_for_note(brain.current_text)

    async def find_notes(args: dict) -> ToolResult:
        query = str(args.get("query", "")).strip()
        hits = await brain.recall.search(query, [NOTES, TASKS], FIND_K)
        return ToolResult(
            recall_results(query, hits, owner()),
            step=f"looked through your notes for '{query}'",
        )

    async def list_tasks(args: dict) -> ToolResult:
        due = str(args.get("due") or "")
        note = str(args.get("note") or "").strip().lower()
        start, end = due_window(due, brain.memory.clock())
        tasks = []
        for t in brain.memory.index.items(TASKS, limit=100_000):
            if note and note not in str(t.meta.get("note", "")).lower():
                continue
            when = t.meta.get("due")
            if due and (start or end):
                if not when:
                    continue
                if (start and when < start.isoformat()) or (end and when > end.isoformat()):
                    continue
            tasks.append(t)
        tasks.sort(key=lambda t: (t.meta.get("due") or "9999", t.text))
        if not tasks:
            what = f" due {due}" if due else ""
            where = f" in {args.get('note')}" if note else ""
            return ToolResult(f"No open tasks{what}{where} in {owner()}'s notes.")
        lines = [f"- {t.text}" for t in tasks[:TASKS_MAX]]
        more = f"\n... and {len(tasks) - TASKS_MAX} more" if len(tasks) > TASKS_MAX else ""
        return ToolResult(
            f"Open tasks in {owner()}'s notes ({len(tasks)}):\n" + "\n".join(lines) + more,
            step="looked at your tasks",
        )

    async def open_note(args: dict) -> ToolResult:
        name = str(args.get("name", "")).strip()
        settings = brain.settings()
        path = brain.notes.find(settings.nas, name)
        if path is None:
            return ToolResult(f"There's no note called {name}.", ok=False)
        vault = Path(settings.nas.vault or "")
        rel = path.relative_to(vault).as_posix().removesuffix(".md")
        url = f"obsidian://open?vault={quote(vault.name)}&file={quote(rel)}"
        result = await brain.desk.send("open_url", {"url": url}, settings.pc.command_timeout_s)
        if not result.ok:
            return ToolResult(f"It didn't open: {result.detail}", ok=False)
        return ToolResult(f"Done: opened {rel} in Obsidian on the PC.", step=f"opened {rel}")

    async def undo_note(args: dict) -> ToolResult:
        settings = brain.settings()
        try:
            done = await asyncio.to_thread(undo, settings.nas, undo_dir(brain))
        except NoteError as e:
            return ToolResult(f"Not done: {e}.", ok=False)
        await asyncio.to_thread(brain.notes.sync, settings.nas)
        return ToolResult(f"Done: {done}.", step="undid my last change to your notes")

    def can_write() -> bool:
        from kit.brain import NOTE_DONE

        # Not when a plain note request was already carried out this turn.
        return ctx().notes and not NOTE_DONE.get()

    def can_undo() -> bool:
        return ctx().notes and last_undo(undo_dir(brain)) is not None

    def context() -> list[str]:
        settings = brain.settings()
        if not settings.nas.vault:
            return []
        return shape_lines(brain.notes.shape(settings.nas, settings.notes))

    note_arg = {"note": {"type": "string", "description": "The note's name or path."}}
    return Pack(
        "notes",
        "your notes vault: find, list tasks, add to, change, tick off, start, open, undo",
        words=[
            "note",
            "notes",
            "vault",
            "obsidian",
            "task",
            "tasks",
            "to-do",
            "todo",
            "to do list",
            "tick",
            "tick off",
            "checklist",
            "journal",
            "daily note",
            "planner",
            "undo that",
        ],
        questions=[
            "What's on my to-do list?",
            "Add this under This Week in the Riverbend log",
            "Tick off the filament task",
            "Anything due this week in my notes?",
            "Open my holiday planner in Obsidian",
            "Start a new note for the shed build",
        ],
        systems=["obsidian"],
        context=context,
        cases=[
            EvalCase("What's on my to-do list this week?", "list_tasks"),
            EvalCase(
                "Tick off order filament in my shopping list",
                "tick_task",
                {"task": "filament"},
            ),
            EvalCase("Find my notes about the shed build", "find_notes", {"query": "shed"}),
            EvalCase("Open my holiday planner in Obsidian", "open_note", {"name": "holiday"}),
        ],
        tools=[
            Tool(
                "find_notes",
                "Search the owner's notes and their open tasks by words and meaning. Use it "
                "to find which note says something; read_note reads one whole.",
                find_notes,
                {"query": {"type": "string", "description": "What to look for."}},
                ["query"],
                offered=lambda: ctx().notes,
                examples=[{"query": "shed build"}],
            ),
            Tool(
                "list_tasks",
                "The open tasks (- [ ] lines) in the owner's notes, soonest due first. due: "
                "today, tomorrow, this week, next week, overdue, or empty for all; note: only "
                "that note's.",
                list_tasks,
                {
                    "due": {"type": "string", "description": "today, this week, overdue..."},
                    **{"note": {"type": "string", "description": "Only this note's tasks."}},
                },
                offered=lambda: ctx().notes,
                examples=[{"due": "this week"}],
            ),
            Tool(
                "append_note",
                "Add text to the end of an existing note, or under one of its headings "
                "(section). Only when the owner asked for it written down.",
                run_change("append_note"),
                {
                    **note_arg,
                    "text": {"type": "string", "description": "What to add, as markdown."},
                    "section": {"type": "string", "description": "A heading in the note."},
                },
                ["note", "text"],
                effect="act",
                offered=can_write,
                ask="add that to {note}",
                confirm_if=asked,
                preview=preview_for("append_note"),
                examples=[
                    {"note": "Riverbend log", "section": "This Week", "text": "- check the spigot"}
                ],
            ),
            Tool(
                "edit_note",
                "Change one bit of a note: find must appear exactly once in it, and is "
                "replaced. Always asks first, showing the change.",
                run_change("edit_note"),
                {
                    **note_arg,
                    "find": {"type": "string", "description": "The exact words now in the note."},
                    "replace": {"type": "string", "description": "What they become."},
                },
                ["note", "find", "replace"],
                effect="change",
                offered=can_write,
                ask="change '{find}' to '{replace}' in {note}",
                preview=preview_for("edit_note"),
            ),
            Tool(
                "tick_task",
                "Tick off one open task, found by some of its words. note may be empty when "
                "only one note has a task like that. Always asks first.",
                run_change("tick_task"),
                {
                    **note_arg,
                    "task": {"type": "string", "description": "Words from the task."},
                },
                ["task"],
                effect="change",
                offered=can_write,
                ask="tick off '{task}'",
                preview=preview_for("tick_task"),
                examples=[{"note": "Shopping list", "task": "filament"}],
            ),
            Tool(
                "new_note",
                "Start a new note, in a folder of the vault (empty: the usual notes folder), "
                "from a template when one is named. Only when the owner asked for it.",
                run_change("new_note"),
                {
                    "title": {"type": "string", "description": "The note's name."},
                    "folder": {"type": "string", "description": "A folder in the vault."},
                    "template": {"type": "string", "description": "A template's name."},
                    "text": {"type": "string", "description": "What it starts with."},
                },
                ["title"],
                effect="act",
                offered=can_write,
                ask="start a note called {title}",
                confirm_if=asked,
                preview=preview_for("new_note"),
            ),
            Tool(
                "open_note",
                "Open one of the owner's notes in Obsidian on their PC.",
                open_note,
                {"name": {"type": "string", "description": "The note's name or path."}},
                ["name"],
                effect="act",
                offered=lambda: ctx().notes and ctx().desk,
                examples=[{"name": "Holiday planner"}],
            ),
            Tool(
                "undo_note",
                "Undo your last change to the owner's notes, putting that note back as it was. "
                "Always asks first.",
                undo_note,
                effect="change",
                offered=can_undo,
                ask="undo my last change to your notes",
            ),
        ],
    )
