"""Kit's conversation loop.

Each turn:

1. Route: pick who answers. The routing mode sets the default (the local model,
   or the cloud ``work`` model in cloud-first), and Dan can say "keep it local",
   "ask Claude" or "think hard" to choose for one message.
2. Recall: search memory (facts, past days, old conversations) for anything
   relevant to the message, and put it in the prompt.
3. Answer. The local model's words stream out as they arrive; a cloud model
   answers in one piece. Both answer in the same JSON, as the same Kit.
4. Act on the reply's action:
   - recall: Kit searches memory for something specific, then answers again;
   - remember: the fact is learned, merging with or updating what Kit knew;
   - thing: a named thing goes in the register of things. A new name becomes a
     suggestion Dan confirms with a quick "yes" (or on the memory page); a link
     for a known thing ("no, it's in Tax/2023") corrects the entry;
   - ask_cloud / ask_expert: the question goes to the work or expert model.
   If a cloud model can't answer (offline, no key, budget used up), the local
   model answers instead when ``routing.fallback_to_local`` is on.
5. Index the exchange so it can be found later.

Settings are read on every turn, so model, routing and persona changes apply at once.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable

from kit.cloud import Cloud, CloudError
from kit.learning import Learner
from kit.local_model import LocalModel, LocalModelError
from kit.memory import CONVERSATION, DAYS, FACTS, RECALL_STEP, Memory, Message
from kit.prompt import history_messages, recall_results, system_prompt
from kit.recall import Recall, Recalled
from kit.reply import (
    Reply,
    ReplyError,
    SayExtractor,
    parse_cloud_reply,
    parse_reply,
    reply_json,
    reply_schema,
)
from kit.settings import Settings
from kit.things import THINGS, Register

log = logging.getLogger(__name__)

Event = dict
LOCAL, WORK, EXPERT = "local", "work", "expert"
DEEP_RECALL = 10

# A short answer to "shall I add it?" that confirms or rejects a suggested thing.
# The whole message must be the answer, so "ok, open VS Code" isn't a yes.
_END = r"(,? (please|thanks|mate|kit))?[.!]*"
YES = re.compile(rf"(yes|yep|yeah|yup|sure|ok|okay|do it|add it|go ahead){_END}", re.I)
NO = re.compile(rf"(no|nope|nah|skip it|don'?t|leave it|no thanks){_END}", re.I)

# Ways to choose who answers one message.
KEEP_LOCAL = re.compile(
    r"\b(keep (it|this) local|answer (it )?locally|don'?t ask (claude|the cloud|anyone))\b",
    re.IGNORECASE,
)
ASK_EXPERT = re.compile(r"\b(think (really )?(hard|carefully)|ask (the|your) expert)\b", re.I)
ASK_CLOUD = re.compile(r"\b(ask (claude|gpt|gemini|the cloud)|use the cloud)\b", re.IGNORECASE)


def route(text: str, settings: Settings) -> tuple[str, bool]:
    """Who answers first: (role, whether Dan chose it for this message)."""
    if KEEP_LOCAL.search(text):
        return LOCAL, True
    if ASK_EXPERT.search(text):
        return EXPERT, True
    if ASK_CLOUD.search(text):
        return WORK, True
    return (WORK if settings.routing.mode == "cloud-first" else LOCAL), False


class Brain:
    def __init__(
        self,
        settings: Callable[[], Settings],
        memory: Memory,
        model: LocalModel,
        cloud: Cloud,
        recall: Recall,
    ) -> None:
        self.settings = settings
        self.memory = memory
        self.model = model
        self.cloud = cloud
        self.recall = recall
        self.learner = Learner(memory, recall, model)
        self.register = Register(memory)
        self.pending_thing: int | None = None

    async def chat(self, text: str) -> AsyncIterator[Event]:
        text = text.strip()
        if not text:
            return
        settings = self.settings()
        history = self.memory.recent(settings.brain.history_messages)
        user_id = self.memory.add_message("user", text)
        answered = self._answer_suggestion(text)
        if answered is not None:
            for event in self._say_locally(answered):
                yield event
            self.memory.index_exchange(
                user_id, settings.persona.owner, text, settings.persona.name, answered.text
            )
            return
        recent_refs = {str(m.id) for m in history if m.role == "user"}
        recalled = await self.recall.for_turn(text, recent_refs)
        role, chosen = route(text, settings)
        said: list[str] = []

        if role != LOCAL and chosen:
            name = settings.profile(role).name
            reply = Reply.plain(f"Sure, asking {name}.", "thinking", "nod")
            self._remember_reply(reply, LOCAL)
            yield {"type": "say", "text": reply.text}
            yield {"type": "reply", "source": LOCAL, "reply": reply.model_dump()}
        async for event in self._converse(text, history, recalled, settings, role, chosen):
            yield self._track(event, said)

        if said:
            self.memory.index_exchange(
                user_id, settings.persona.owner, text, settings.persona.name, " ".join(said)
            )
            await self.recall.index_pending()

    def _answer_suggestion(self, text: str) -> Reply | None:
        """If Kit just suggested a thing and Dan answers yes or no, act on it without
        asking a model. Anything else leaves the suggestion for the memory page."""
        pending, self.pending_thing = self.pending_thing, None
        if pending is None:
            return None
        thing = self.register.get(pending)
        if thing is None or not thing.suggested:
            return None
        if YES.fullmatch(text):
            self.register.confirm(pending)
            return Reply.plain(f"Done, {thing.name} is in the register.", "happy", "nod")
        if NO.fullmatch(text):
            self.register.reject(pending)
            return Reply.plain(f"Okay, I'll leave {thing.name} out.", "neutral", "nod")
        return None

    def _say_locally(self, reply: Reply) -> list[Event]:
        message_id = self._remember_reply(reply, LOCAL)
        return [
            {"type": "say", "text": reply.text},
            {
                "type": "reply",
                "source": LOCAL,
                "reply": reply.model_dump(),
                "message_id": message_id,
            },
        ]

    def _note_thing(self, reply: Reply) -> Event | None:
        """Act on a ``thing`` action: update a known thing's link, or suggest a new one."""
        a = reply.action
        name = a.text.strip()
        if not name:
            return None
        link = (
            []
            if a.link_system == "none" or not a.link_target.strip()
            else [{"system": a.link_system, "target": a.link_target}]
        )
        known = self.register.named(name)
        if known:
            if not link:
                return None
            new_id = self.register.set_link(known.id, a.link_system, a.link_target)
            thing = self.register.get(new_id)
            return {"type": "thing_updated", "thing": thing.as_dict() if thing else None}
        thing = self.register.suggest(name, a.thing_kind, link)
        self.pending_thing = thing.id
        return {"type": "thing_suggested", "thing": thing.as_dict()}

    @staticmethod
    def _track(event: Event, said: list[str]) -> Event:
        if event["type"] == "reply":
            said.append(Reply.model_validate(event["reply"]).full_text)
        return event

    def _system(self, settings: Settings, recalled: Recalled, role: str, hand_off: bool) -> str:
        routing = settings.routing
        work, expert = settings.profile(WORK), settings.profile(EXPERT)
        if role == LOCAL:
            helper, further, web = (work.name if hand_off else None), None, False
        elif role == WORK:
            different = routing.expert != routing.work
            helper, further, web = None, (expert.name if different else None), work.web_search
        else:
            helper, further, web = None, None, expert.web_search
        return system_prompt(
            settings.persona,
            recalled,
            self.memory.clock(),
            role=role,
            mode=routing.mode,
            helper=helper,
            expert=further,
            web_search=web,
        )

    async def _converse(
        self,
        text: str,
        history: list[Message],
        recalled: Recalled,
        settings: Settings,
        role: str,
        chosen: bool = False,
        hops: int = 0,
    ) -> AsyncIterator[Event]:
        hand_off = role == LOCAL and not chosen and hops == 0
        messages = [
            {"role": "system", "content": self._system(settings, recalled, role, hand_off)},
            *history_messages(history),
            {"role": "user", "content": text},
        ]
        try:
            reply, message_id = None, None
            async for event in self._reply(messages, role, settings, text):
                if event["type"] == "reply":
                    reply = Reply.model_validate(event["reply"])
                    message_id = event["message_id"]
                yield event
            if reply is None:
                return

            if reply.action.kind == "recall":
                query = reply.action.text.strip() or text
                hits = await self.recall.search(
                    query, [FACTS, DAYS, CONVERSATION, THINGS], DEEP_RECALL
                )
                yield {"type": "recalled", "query": query, "found": len(hits)}
                messages += [
                    {"role": "assistant", "content": reply_json(reply)},
                    {
                        "role": "user",
                        "content": recall_results(query, hits, settings.persona.owner),
                    },
                ]
                # The "Let me think..." turn is kept as a working note (RECALL_STEP), so
                # later history shows one answer per message, not a recall habit.
                self.memory.set_message_source(message_id, RECALL_STEP)
                reply = None
                async for event in self._reply(messages, role, settings, text):
                    if event["type"] == "reply":
                        reply = Reply.model_validate(event["reply"])
                    yield event
                if reply is None:
                    return
        except CloudError as e:
            async for event in self._cloud_failed(e, text, history, recalled, settings, chosen):
                yield event
            return

        kind = reply.action.kind
        if kind == "remember" and reply.action.text.strip():
            learned = await self.learner.learn(
                reply.action.text, reply.action.category, settings.persona.owner
            )
            yield {
                "type": "remembered",
                "fact": learned.text,
                "decision": learned.decision,
                "replaced": learned.replaced,
            }
        elif kind == "thing":
            event = self._note_thing(reply)
            if event:
                yield event
        elif (kind == "ask_cloud" and hand_off) or (kind == "ask_expert" and role == WORK):
            to = WORK if kind == "ask_cloud" else EXPERT
            question = reply.action.text.strip() or text
            yield {"type": "handing_off", "to": settings.profile(to).name, "question": question}
            async for event in self._converse(
                text, history, recalled, settings, to, chosen, hops + 1
            ):
                yield event

    async def _cloud_failed(
        self,
        error: CloudError,
        text: str,
        history: list[Message],
        recalled: Recalled,
        settings: Settings,
        chosen: bool,
    ) -> AsyncIterator[Event]:
        """A cloud model couldn't answer. Unless Dan asked for it by name, the local
        model has a go instead (when fallback is on); otherwise Kit says why."""
        if settings.routing.fallback_to_local and not chosen:
            yield {"type": "notice", "message": f"{error} I'll answer myself."}
            async for event in self._converse(
                text, history, recalled, settings, LOCAL, chosen=True, hops=1
            ):
                yield event
            return
        reply = Reply.plain(str(error), "concerned", "shrug")
        message_id = self._remember_reply(reply, LOCAL)
        yield {"type": "say", "text": reply.text}
        yield {
            "type": "reply",
            "source": LOCAL,
            "reply": reply.model_dump(),
            "message_id": message_id,
        }

    async def _reply(
        self, messages: list[dict], role: str, settings: Settings, question: str
    ) -> AsyncIterator[Event]:
        if role == LOCAL:
            async for event in self._local_reply(messages, LOCAL):
                yield event
            return
        profile = settings.profile(role)
        if profile.provider == "ollama":
            async for event in self._local_reply(messages, LOCAL, profile.model):
                yield event
            return
        answer = await self.cloud.answer(profile, messages, settings, question)
        reply = parse_cloud_reply(answer.text)
        if answer.truncated:
            reply.detail = reply.detail + "\n\n(I ran out of room there; ask me to continue.)"
        message_id = self._remember_reply(reply, "cloud")
        yield {"type": "say", "text": reply.text, "source": "cloud"}
        yield {
            "type": "reply",
            "source": "cloud",
            "role": role,
            "model": answer.model,
            "label": profile.name,
            "reply": reply.model_dump(),
            "message_id": message_id,
            "cost_usd": round(answer.cost_usd, 4),
            "searches": answer.searches,
            "month_usd": round(self.memory.month_spend(), 4),
        }

    async def _local_reply(
        self, messages: list[dict], source: str, model: str | None = None
    ) -> AsyncIterator[Event]:
        extractor = SayExtractor()
        raw, said = [], []
        try:
            async for piece in self.model.stream(messages, reply_schema(), model):
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
            "source": source,
            "reply": reply.model_dump(),
            "message_id": message_id,
        }

    def _remember_reply(self, reply: Reply, source: str) -> int:
        return self.memory.add_message("kit", reply.full_text, reply_json(reply), source)

    async def summarise_past_days(self) -> list[str]:
        """Summarise each finished day and learn its facts. Returns the days done."""
        done = []
        persona = self.settings().persona
        for day in self.memory.days_to_summarise():
            if not await self.learner.summarise_day(day, persona.owner, persona.name):
                break
            done.append(day)
        return done
