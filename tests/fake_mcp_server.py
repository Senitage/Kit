"""A made-up app's MCP server for the tests (kit.mcp_client, kit.tools.mcp): a
trip planner with a read, a write that's harmless, one that changes things, one
that says nothing about itself, a picture and its saved work. Run as a program it
talks stdio; ``Server.handle`` answers one message in-process."""

from __future__ import annotations

import json
import sys

ROWS = [
    {"kind": "trip", "ref": "trip:7", "text": "Riverbend trip, 3 stops, leaves 14 Nov", "id": 7},
    {"kind": "calc", "ref": "calc:12", "text": "Slurry pump duty, 300 m3/h at 35 m, rev B"},
]


def _tool(name, description, props=None, required=(), **annotations):
    spec = {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": props or {}, "required": list(required)},
    }
    if annotations:
        spec["annotations"] = annotations
    return spec


class Server:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.extra = False  # "grow" adds a tool and says the list changed
        self.stops = ["Richmond"]

    def tools(self) -> list[dict]:
        tools = [
            _tool("list_trips", "The trips planned.", readOnlyHint=True),
            _tool(
                "add_stop",
                "Add a stop to a trip.",
                {"trip": {"type": "string"}, "place": {"type": "string"}},
                ["trip", "place"],
                destructiveHint=True,
            ),
            _tool("mark_packed", "Mark the bags packed.", destructiveHint=False),
            _tool("grow", "Learn a new trick."),
            _tool("picture", "A map of the trip.", readOnlyHint=True),
            _tool("contents", "Every saved thing, as rows.", readOnlyHint=True),
        ]
        if self.extra:
            tools.append(_tool("new_trick", "A trick learned since.", readOnlyHint=True))
        return tools

    def handle(self, message: dict) -> list[dict]:
        """The messages sent back for one message: notifications, then the answer."""
        method = message.get("method")
        if "id" not in message:
            return []
        out: list[dict] = []

        def answer(result=None, error=None):
            body = {"jsonrpc": "2.0", "id": message["id"]}
            body.update({"error": error} if error else {"result": result})
            out.append(body)
            return out

        params = message.get("params") or {}
        if method == "initialize":
            return answer(
                {
                    "protocolVersion": params.get("protocolVersion"),
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "trips", "title": "Trip Planner", "version": "1"},
                }
            )
        if method == "tools/list":
            tools = self.tools()
            if not params.get("cursor"):  # two pages
                return answer({"tools": tools[:3], "nextCursor": "p2"})
            return answer({"tools": tools[3:]})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            self.calls.append((name, args))
            if name == "list_trips":
                text = "Riverbend trip: " + ", ".join(self.stops)
                return answer({"content": [{"type": "text", "text": text}]})
            if name == "add_stop":
                self.stops.append(args["place"])
                return answer({"content": [{"type": "text", "text": f"Added {args['place']}."}]})
            if name == "mark_packed":
                return answer({"content": [], "structuredContent": {"packed": True}})
            if name == "grow":
                self.extra = True
                out.append({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
                return answer({"content": [{"type": "text", "text": "Learned."}]})
            if name == "picture":
                image = {"type": "image", "data": "A" * 4096, "mimeType": "image/png"}
                return answer({"content": [{"type": "text", "text": "Here's the map."}, image]})
            if name == "contents":
                return answer({"content": [], "structuredContent": {"rows": ROWS}})
            if name == "quit":
                sys.exit(0)
            return answer(
                {"content": [{"type": "text", "text": f"No tool {name}."}], "isError": True}
            )
        return answer(error={"code": -32601, "message": f"no method {method}"})


def main() -> None:
    server = Server()
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("method") == "tools/call" and message["params"]["name"] == "quit":
            return
        for out in server.handle(message):
            sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
