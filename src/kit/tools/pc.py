"""The ``pc`` pack: doing things on Dan's PC and knowing what he's worked on. The
open tools ask the desk app through a ``desk_command`` (kit.desk_commands), which
does only what its own rules on the PC allow (the folders and apps in its "What
Kit may open" list) and says why when it won't; they're offered only while a desk
app is reporting. ``recent_work`` reads the day notes in memory (kit.activity) and
``list_projects`` the code projects (kit.projects), so both work with the PC off.
See docs/2 How Kit Works/Desk App.md."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kit.activity import recent_work as activity_lines
from kit.files import FILES
from kit.projects import PROJECTS, pc_path
from kit.tools import EvalCase, Pack, Tool, ToolResult

if TYPE_CHECKING:
    from kit.brain import Brain
    from kit.desk_commands import CommandResult

MEDIA = ["play_pause", "next", "previous", "volume_up", "volume_down", "mute"]
SHOW_MAX = 5


def _join(base: str, rel: str) -> str:
    """A root's folder and a file's root-relative path, in the folder's own style."""
    windows = "\\" in base or (len(base) > 1 and base[1] == ":")
    sep = "\\" if windows else "/"
    return base.rstrip("/\\") + sep + rel.replace("/", sep)


def pc_pack(brain: Brain) -> Pack:
    def owner() -> str:
        return brain.settings().persona.owner

    def said(result: CommandResult, done: str) -> ToolResult:
        from kit.brain import CHANNEL

        if not result.ok:
            return ToolResult(f"It didn't happen: {result.detail}", ok=False)
        where = ""
        if CHANNEL.get() == "phone":
            where = f" It's on {owner()}'s PC, not their phone: say it's open on their PC."
        detail = f" ({result.detail})" if result.detail else ""
        return ToolResult(f"Done: {done}{detail}.{where}", step=done)

    async def send(kind: str, args: dict) -> CommandResult:
        timeout = brain.settings().pc.command_timeout_s
        return await brain.desk.send(kind, args, timeout)

    async def open_path(args: dict) -> ToolResult:
        path = str(args.get("path", "")).strip()
        return said(await send("open_path", {"path": path}), f"opened {path} on the PC")

    def document_path(ref: str) -> str | None:
        ref = ref.strip().strip("[]").split(", page", 1)[0]
        pieces = brain.memory.index.with_ref(FILES, ref)
        if not pieces:
            return None
        meta = pieces[0].meta
        root = brain.settings().files.roots.get(meta.get("root", ""))
        if root is None:
            return None
        return _join(root.pc_path or root.path, meta.get("rel", ""))

    async def open_document(args: dict) -> ToolResult:
        ref = str(args.get("ref", "")).strip()
        path = document_path(ref)
        if path is None:
            return ToolResult(
                f"There's no file '{ref}' in the index; find it with find_documents first.",
                ok=False,
            )
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return said(await send("open_path", {"path": path}), f"opened {name} on the PC")

    async def open_app(args: dict) -> ToolResult:
        name = str(args.get("name", "")).strip()
        extra = [str(a) for a in args.get("args") or []][:5]
        return said(await send("open_app", {"name": name, "args": extra}), f"opened {name}")

    async def open_url(args: dict) -> ToolResult:
        url = str(args.get("url", "")).strip()
        return said(await send("open_url", {"url": url}), f"opened {url} on the PC")

    async def show(args: dict) -> ToolResult:
        paths = [str(p).strip() for p in args.get("paths") or [] if str(p).strip()]
        if not paths:
            return ToolResult("Nothing to show: give one or more paths.", ok=False)
        paths = [document_path(p) or p for p in paths[:SHOW_MAX]]
        return said(await send("show", {"paths": paths}), f"opened {len(paths)} on the PC")

    async def focus(args: dict) -> ToolResult:
        window = str(args.get("window", "")).strip()
        return said(await send("focus", {"window": window}), f"brought {window} to the front")

    async def media(args: dict) -> ToolResult:
        action = str(args.get("action", "")).strip()
        if action not in MEDIA:
            return ToolResult(f"The media actions are {', '.join(MEDIA)}.", ok=False)
        return said(await send("media", {"action": action}), action.replace("_", " "))

    async def recent_work(args: dict) -> ToolResult:
        when = str(args.get("when", "") or "yesterday")
        text = activity_lines(brain.memory.index, when, brain.memory.clock())
        projects = brain.memory.index.items(PROJECTS, limit=500)
        if projects:
            text += "\nCode projects, latest commit first:\n" + "\n".join(
                f"- {p.title}: {p.meta.get('last_commit') or 'no commits'}"
                for p in sorted(
                    projects, key=lambda p: p.meta.get("last_commit", ""), reverse=True
                )[:5]
            )
        return ToolResult(
            f"What {owner()} did on the PC ({when}):\n{text}",
            step=f"looked back at {when} on your PC",
        )

    async def list_projects(args: dict) -> ToolResult:
        query = str(args.get("query", "") or "").strip()
        if query:
            items = [h.item for h in await brain.recall.search(query, [PROJECTS], 8)]
        else:
            items = brain.memory.index.items(PROJECTS, limit=200)
        if not items:
            return ToolResult(
                "No code projects are known"
                + (f" matching '{query}'." if query else " (projects.roots is empty)."),
                ok=bool(query),
            )
        lines = [f"- {i.title}: {i.text[len('Code project ' + i.title) :].strip()}" for i in items]
        return ToolResult("Code projects:\n" + "\n".join(lines), step="looked at your projects")

    async def open_project(args: dict) -> ToolResult:
        name = str(args.get("name", "")).strip()
        items = brain.memory.index.items(PROJECTS, limit=500)
        match = next((i for i in items if i.title.lower() == name.lower()), None)
        if match is None and name:
            hits = await brain.recall.search(name, [PROJECTS], 1)
            match = hits[0].item if hits else None
        if match is None:
            return ToolResult(f"There's no project called {name}.", ok=False)
        s = brain.settings().projects
        path = pc_path(match.meta.get("path", ""), s.pc_roots)
        result = await send("open_app", {"name": s.editor, "args": [path]})
        return said(result, f"opened {match.title} in {s.editor}")

    def online() -> bool:
        return brain.tool_context.desk

    def has_projects() -> bool:
        return brain.tool_context.projects

    return Pack(
        "pc",
        "the owner's PC: open files, folders, apps and sites; what they've worked on",
        words=[
            "open",
            "bring up",
            "launch",
            "show me",
            "focus",
            "pause",
            "music",
            "volume",
            "mute",
            "working on",
            "worked on",
            "project",
            "projects",
            "yesterday",
        ],
        questions=[
            "Bring up the projects I worked on",
            "Open the Riverbend folder",
            "What was I working on last Tuesday?",
            "Open Excel",
            "Pause the music",
            "Show me the rates notice",
            "Open the Pod project in VS Code",
        ],
        systems=["code"],
        cases=[
            EvalCase("What was I working on yesterday?", "recent_work", {"when": "yesterday"}),
            EvalCase("Pause the music", "media", {"action": "play_pause"}),
            EvalCase("Open Excel", "open_app", {"name": "excel"}),
            EvalCase("Open github.com", "open_url", {"url": "github.com"}),
        ],
        tools=[
            Tool(
                "open_path",
                "Open a folder or file on the owner's PC (in Explorer or its own app). The "
                "path is as the PC sees it, like C:\\Users\\Dan\\Documents or a \\\\NAS "
                "share. For a document found with find_documents, use open_document.",
                open_path,
                {"path": {"type": "string", "description": "The folder or file on the PC."}},
                ["path"],
                effect="act",
                offered=online,
                speak="You're about to open something on {owner}'s PC. Say so in a few words.",
            ),
            Tool(
                "open_document",
                "Open on the PC a document found with find_documents, by its place.",
                open_document,
                {"ref": {"type": "string", "description": "The place, like finance:Rates/a.pdf."}},
                ["ref"],
                effect="act",
                offered=online,
            ),
            Tool(
                "open_app",
                "Start an app on the PC by its short name in the desk app's list (excel, "
                "code, notepad, explorer, browser). args are what to open in it.",
                open_app,
                {
                    "name": {"type": "string", "description": "The app's short name."},
                    "args": {"type": "array", "items": {"type": "string"}},
                },
                ["name"],
                effect="act",
                offered=online,
            ),
            Tool(
                "open_url",
                "Open a web page (http or https) in the PC's browser.",
                open_url,
                {"url": {"type": "string", "description": "The address."}},
                ["url"],
                effect="act",
                offered=online,
            ),
            Tool(
                "show",
                "Open several folders or files on the PC at once (up to five), like the "
                "folders of yesterday's projects.",
                show,
                {"paths": {"type": "array", "items": {"type": "string"}}},
                ["paths"],
                effect="act",
                offered=online,
            ),
            Tool(
                "focus",
                "Bring an open window to the front, by (part of) its title.",
                focus,
                {"window": {"type": "string", "description": "Words from the window's title."}},
                ["window"],
                effect="act",
                offered=online,
            ),
            Tool(
                "media",
                "Control what's playing on the PC: play_pause, next, previous, volume_up, "
                "volume_down or mute.",
                media,
                {"action": {"type": "string", "enum": MEDIA}},
                ["action"],
                effect="act",
                offered=online,
            ),
            Tool(
                "recent_work",
                "What the owner did on the PC on a day or a week: apps and how long, files, "
                "sites and projects, and the code projects' latest commits. when is words "
                "like yesterday, last Tuesday, last week.",
                recent_work,
                {"when": {"type": "string", "description": "The day or week, in words."}},
                offered=lambda: brain.tool_context.activity,
                examples=[{"when": "yesterday"}, {"when": "last week"}],
            ),
            Tool(
                "list_projects",
                "The owner's code projects (what each is for, its last commit), or those "
                "matching query.",
                list_projects,
                {"query": {"type": "string", "description": "Words to match, or empty."}},
                offered=has_projects,
            ),
            Tool(
                "open_project",
                "Open one of the owner's code projects in their editor on the PC.",
                open_project,
                {"name": {"type": "string", "description": "The project's name."}},
                ["name"],
                effect="act",
                offered=lambda: online() and has_projects(),
            ),
        ],
    )
