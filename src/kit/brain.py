"""Kit's conversation loop.

Each message goes to the local model, whose reply streams back as events: the
spoken words as they arrive, then the whole structured reply. If the reply
asks for Claude (or Dan said "ask Claude"), Claude's answer follows as a second
reply. Settings are read on every turn, so persona changes apply at once.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable

from kit.expert import Expert
from kit.local_model import LocalModel, LocalModelError
from kit.memory import Memory
from kit.prompt import history_messages, system_prompt
from kit.reply import Reply, ReplyError, SayExtractor, parse_reply, reply_json, reply_schema
from kit.settings import Settings

Event = dict
ASK_CLAUDE = re.compile(r"\bask\s+claude\b", re.IGNORECASE)
FACTS_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {"type": "string"}, "maxItems": 10}},
    "required": ["facts"],
    "additionalProperties": False,
}


class Brain:
    def __init__(
        self,
        settings: Callable[[], Settings],
        memory: Memory,
        model: LocalModel,
        expert: Expert,
    ) -> None:
        self.settings = settings
        self.memory = memory
        self.model = model
        self.expert = expert

    async def chat(self, text: str) -> AsyncIterator[Event]:
        text = text.strip()
        if not text:
            return
        settings = self.settings()
        history = self.memory.recent(settings.brain.history_messages)
        self.memory.add_message("user", text)

        if ASK_CLAUDE.search(text):
            reply = Reply.plain("Sure, asking Claude.", "thinking", "nod")
            self._remember_reply(reply, "local")
            yield {"type": "say", "text": reply.text}
            yield {"type": "reply", "source": "local", "reply": reply.model_dump()}
            async for event in self._ask_claude(text, history, settings):
                yield event
            return

        reply = None
        async for event in self._local_reply(text, history, settings):
            if event["type"] == "reply":
                reply = Reply.model_validate(event["reply"])
            yield event
        if reply is None:
            return
        if reply.action.kind == "remember" and reply.action.text.strip():
            self.memory.add_fact(reply.action.text.strip())
            yield {"type": "remembered", "fact": reply.action.text.strip()}
        elif reply.action.kind == "ask_claude":
            question = reply.action.text.strip() or text
            async for event in self._ask_claude(question, history, settings):
                yield event

    async def _local_reply(self, text: str, history, settings: Settings) -> AsyncIterator[Event]:
        messages = [
            {
                "role": "system",
                "content": system_prompt(
                    settings.persona,
                    self.memory.facts(settings.brain.facts_in_prompt),
                    self.memory.clock(),
                ),
            },
            *history_messages(history),
            {"role": "user", "content": text},
        ]
        extractor = SayExtractor()
        raw, said = [], []
        try:
            async for piece in self.model.stream(messages, reply_schema()):
                raw.append(piece)
                spoken = extractor.feed(piece)
                if spoken:
                    said.append(spoken)
                    yield {"type": "say", "text": spoken}
        except LocalModelError as e:
            yield {"type": "error", "message": f"My local brain isn't answering: {e}"}
            return
        try:
            reply = parse_reply("".join(raw))
        except ReplyError:
            # The words got through even if the JSON didn't; keep them.
            spoken = "".join(said).strip()
            if not spoken:
                yield {"type": "error", "message": "I lost my train of thought. Say again?"}
                return
            reply = Reply.plain(spoken)
        self._remember_reply(reply, "local")
        yield {"type": "reply", "source": "local", "reply": reply.model_dump()}

    async def _ask_claude(self, question, history, settings: Settings) -> AsyncIterator[Event]:
        yield {"type": "asking_claude", "question": question}
        context = [
            {"role": "user" if m.role == "user" else "assistant", "content": m.text}
            for m in history
        ]
        context = _alternating(context)
        answer = await self.expert.ask(question, context, settings.claude, settings.persona)
        reply = Reply.plain(
            answer.text, "proud" if answer.ok else "concerned", "nod" if answer.ok else "shrug"
        )
        self._remember_reply(reply, "claude")
        yield {"type": "say", "text": answer.text, "source": "claude"}
        yield {
            "type": "reply",
            "source": "claude",
            "reply": reply.model_dump(),
            "model": answer.model,
            "cost_usd": round(answer.cost_usd, 4),
            "month_usd": round(self.memory.month_spend(), 4),
        }

    def _remember_reply(self, reply: Reply, source: str) -> None:
        self.memory.add_message("kit", reply.text, reply_json(reply), source)

    async def summarise_past_days(self) -> list[str]:
        """Turn each finished day's conversation into a few facts. Returns days done."""
        done = []
        settings = self.settings()
        owner = settings.persona.owner
        for day in self.memory.days_to_summarise():
            transcript = "\n".join(
                f"{owner if m.role == 'user' else settings.persona.name}: {m.text}"
                for m in self.memory.messages_on(day)
            )
            messages = [
                {
                    "role": "system",
                    "content": f"From this conversation, list up to 10 short facts worth "
                    f"remembering about {owner}: their work, projects, plans, preferences and "
                    f"anything they asked to be remembered. Each fact is one sentence that "
                    f"makes sense on its own later. Skip small talk. Answer as JSON.",
                },
                {"role": "user", "content": f"Conversation on {day}:\n{transcript[-20000:]}"},
            ]
            try:
                raw = await self.model.complete(messages, FACTS_SCHEMA)
                facts = json.loads(raw)["facts"]
            except (LocalModelError, ValueError, KeyError, TypeError):
                break
            self.memory.save_facts(day, [str(f) for f in facts])
            done.append(day)
        return done


def _alternating(messages: list[dict]) -> list[dict]:
    """Claude wants user and assistant turns to alternate, starting with the user."""
    out: list[dict] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append(dict(m))
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":
        # The question itself is the next user turn, so end on the assistant.
        out.append({"role": "assistant", "content": "(noted)"})
    return out
