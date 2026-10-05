"""Kit's conversation loop.

Each turn:

1. Recall: search memory (facts, past days, old conversations) for anything
   relevant to the message, by words and meaning, and put it in the prompt.
2. Answer with the local model; the spoken words stream out as they arrive.
3. Act on the reply's action:
   - recall: Kit searches memory for something specific, then answers again
     with what it found;
   - remember: the fact is learned, merging with or updating what Kit knew;
   - ask_claude: Claude answers, seeing the same memories.
4. Index the exchange so it can be found later.

Settings are read on every turn, so persona changes apply at once.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable

from kit.expert import Expert
from kit.learning import Learner
from kit.local_model import LocalModel, LocalModelError
from kit.memory import CONVERSATION, DAYS, FACTS, RECALL_STEP, Memory, Message
from kit.prompt import history_messages, memory_block, recall_results, system_prompt
from kit.recall import Recall, Recalled
from kit.reply import Reply, ReplyError, SayExtractor, parse_reply, reply_json, reply_schema
from kit.settings import Settings

log = logging.getLogger(__name__)

Event = dict
ASK_CLAUDE = re.compile(r"\bask\s+claude\b", re.IGNORECASE)
DEEP_RECALL = 10


class Brain:
    def __init__(
        self,
        settings: Callable[[], Settings],
        memory: Memory,
        model: LocalModel,
        expert: Expert,
        recall: Recall,
    ) -> None:
        self.settings = settings
        self.memory = memory
        self.model = model
        self.expert = expert
        self.recall = recall
        self.learner = Learner(memory, recall, model)

    async def chat(self, text: str) -> AsyncIterator[Event]:
        text = text.strip()
        if not text:
            return
        settings = self.settings()
        history = self.memory.recent(settings.brain.history_messages)
        user_id = self.memory.add_message("user", text)
        recent_refs = {str(m.id) for m in history if m.role == "user"}
        recalled = await self.recall.for_turn(text, recent_refs)
        said: list[str] = []

        if ASK_CLAUDE.search(text):
            reply = Reply.plain("Sure, asking Claude.", "thinking", "nod")
            self._remember_reply(reply, "local")
            yield {"type": "say", "text": reply.text}
            yield {"type": "reply", "source": "local", "reply": reply.model_dump()}
            async for event in self._ask_claude(text, history, recalled, settings):
                yield self._track(event, said)
        else:
            async for event in self._converse(text, history, recalled, settings):
                yield self._track(event, said)

        if said:
            self.memory.index_exchange(
                user_id, settings.persona.owner, text, settings.persona.name, " ".join(said)
            )
            await self.recall.index_pending()

    @staticmethod
    def _track(event: Event, said: list[str]) -> Event:
        if event["type"] == "reply":
            said.append(Reply.model_validate(event["reply"]).text)
        return event

    async def _converse(
        self, text: str, history: list[Message], recalled: Recalled, settings: Settings
    ) -> AsyncIterator[Event]:
        messages = [
            {
                "role": "system",
                "content": system_prompt(settings.persona, recalled, self.memory.clock()),
            },
            *history_messages(history),
            {"role": "user", "content": text},
        ]
        reply, message_id = None, None
        async for event in self._local_reply(messages, source="local"):
            if event["type"] == "reply":
                reply = Reply.model_validate(event["reply"])
                message_id = event["message_id"]
            yield event
        if reply is None:
            return

        if reply.action.kind == "recall":
            query = reply.action.text.strip() or text
            hits = await self.recall.search(query, [FACTS, DAYS, CONVERSATION], DEEP_RECALL)
            yield {"type": "recalled", "query": query, "found": len(hits)}
            messages += [
                {"role": "assistant", "content": reply_json(reply)},
                {"role": "user", "content": recall_results(query, hits, settings.persona.owner)},
            ]
            # The "Let me think..." turn is kept as a working note (RECALL_STEP), so
            # later history shows one answer per message, not a recall habit.
            self.memory.set_message_source(message_id, RECALL_STEP)
            reply = None
            async for event in self._local_reply(messages, source="local"):
                if event["type"] == "reply":
                    reply = Reply.model_validate(event["reply"])
                yield event
            if reply is None:
                return

        if reply.action.kind == "remember" and reply.action.text.strip():
            learned = await self.learner.learn(
                reply.action.text, reply.action.category, settings.persona.owner
            )
            yield {
                "type": "remembered",
                "fact": learned.text,
                "decision": learned.decision,
                "replaced": learned.replaced,
            }
        elif reply.action.kind == "ask_claude":
            question = reply.action.text.strip() or text
            async for event in self._ask_claude(question, history, recalled, settings):
                yield event

    async def _local_reply(self, messages: list[dict], source: str) -> AsyncIterator[Event]:
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
        except Exception as e:  # a bug in the stream reader must not drop the chat
            log.exception("reading the local model's reply failed")
            yield {"type": "error", "message": f"I lost my train of thought ({e}). Say again?"}
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
        message_id = self._remember_reply(reply, source)
        yield {
            "type": "reply",
            "source": "local",
            "reply": reply.model_dump(),
            "message_id": message_id,
        }

    async def _ask_claude(
        self, question: str, history: list[Message], recalled: Recalled, settings: Settings
    ) -> AsyncIterator[Event]:
        yield {"type": "asking_claude", "question": question}
        context = [
            {"role": "user" if m.role == "user" else "assistant", "content": m.text}
            for m in history
        ]
        notes = "\n".join(memory_block(recalled, settings.persona.owner)).strip()
        answer = await self.expert.ask(
            question, _alternating(context), settings.claude, settings.persona, notes
        )
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

    def _remember_reply(self, reply: Reply, source: str) -> int:
        return self.memory.add_message("kit", reply.text, reply_json(reply), source)

    async def summarise_past_days(self) -> list[str]:
        """Summarise each finished day and learn its facts. Returns the days done."""
        done = []
        persona = self.settings().persona
        for day in self.memory.days_to_summarise():
            if not await self.learner.summarise_day(day, persona.owner, persona.name):
                break
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
