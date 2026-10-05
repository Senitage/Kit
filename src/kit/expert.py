"""Claude, for questions the local model shouldn't answer alone.

Kit hands a question here when Dan says "ask Claude" or when the local model
decides it's out of its depth. Claude answers in Kit's voice, every call's
estimated cost goes in the spend log, and calls stop once the month's cap is
reached.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import anthropic

from kit.memory import Memory
from kit.settings import ClaudeSettings, PersonaSettings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
ClientFactory = Callable[[str], anthropic.AsyncAnthropic]


@dataclass
class ExpertAnswer:
    text: str
    ok: bool
    model: str = ""
    cost_usd: float = 0.0


def make_async_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key, max_retries=2, timeout=300)


CACHE_WRITE_MULTIPLIER = 1.25  # a 5-minute cache write costs 1.25x input, on every model


def estimate_cost(
    settings: ClaudeSettings,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Cost of one call. ``input_tokens`` is every input token. Of those,
    ``cached_tokens`` were read from the prompt cache at the cheap rate and
    ``cache_write_tokens`` were written to it at 1.25x the input rate."""
    fresh = input_tokens - cached_tokens - cache_write_tokens
    return (
        fresh * settings.input_usd_per_mtok
        + cache_write_tokens * settings.input_usd_per_mtok * CACHE_WRITE_MULTIPLIER
        + cached_tokens * settings.cached_input_usd_per_mtok
        + output_tokens * settings.output_usd_per_mtok
    ) / 1_000_000


def expert_system_prompt(persona: PersonaSettings, memory_notes: str = "") -> str:
    notes = (
        f"\nWhat {persona.name} remembers that may be relevant (dated; newer wins):\n"
        f"{memory_notes}\n"
        if memory_notes
        else ""
    )
    return (
        f"You are answering as {persona.name}, {persona.owner}'s personal assistant. "
        f"{persona.backstory} {persona.knows}\n"
        f"How {persona.name} talks: {persona.speech}\n"
        f"The local model passed this question to you because it was too hard. "
        f"Answer it properly and correctly, in {persona.name}'s voice. Lead with the answer. "
        f"Use plain text that reads well aloud: short paragraphs, no tables, and code only "
        f"when code was asked for."
        f"{notes}"
    )


class Expert:
    def __init__(
        self,
        memory: Memory,
        api_key: Callable[[], str | None],
        make_client: ClientFactory = make_async_client,
    ) -> None:
        self.memory = memory
        self.api_key = api_key
        self.make_client = make_client

    async def ask(
        self,
        question: str,
        context: list[dict],
        claude: ClaudeSettings,
        persona: PersonaSettings,
        memory_notes: str = "",
    ) -> ExpertAnswer:
        spent = self.memory.month_spend()
        if spent >= claude.monthly_cap_usd:
            return ExpertAnswer(
                f"I've hit this month's Claude budget (${spent:.2f} of "
                f"${claude.monthly_cap_usd:.2f}), so I can't ask. You can raise the cap "
                "in my settings.",
                ok=False,
            )
        key = self.api_key()
        if not key:
            return ExpertAnswer(
                "I can't reach Claude: there's no API key set up. See the stage 0 guide.",
                ok=False,
            )
        client = self.make_client(key)
        try:
            response = await client.beta.messages.create(
                model=claude.model,
                max_tokens=claude.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": expert_system_prompt(persona, memory_notes),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[*context, {"role": "user", "content": question}],
                output_config={"effort": claude.effort},
                fallbacks="default",
                betas=[FALLBACK_BETA],
            )
        except anthropic.AuthenticationError:
            return ExpertAnswer("Claude rejected my API key, so I couldn't ask.", ok=False)
        except anthropic.RateLimitError:
            return ExpertAnswer("Claude is rate-limiting me right now. Try again soon.", ok=False)
        except anthropic.APIConnectionError:
            return ExpertAnswer("I couldn't reach Claude. Is the internet up?", ok=False)
        except anthropic.APIStatusError as e:
            return ExpertAnswer(f"Claude returned an error ({e.status_code}).", ok=False)
        finally:
            await client.close()

        usage = response.usage
        input_tokens = (
            usage.input_tokens
            + (usage.cache_creation_input_tokens or 0)
            + (usage.cache_read_input_tokens or 0)
        )
        cost = estimate_cost(
            claude,
            input_tokens,
            usage.output_tokens,
            cached_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
        )
        self.memory.record_spend(response.model, input_tokens, usage.output_tokens, cost, question)
        if response.stop_reason == "refusal":
            return ExpertAnswer(
                "Claude declined to answer that one.",
                ok=False,
                model=response.model,
                cost_usd=cost,
            )
        text = "\n\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n(Claude ran out of room there; ask me to continue.)"
        return ExpertAnswer(
            text or "Claude came back empty.", ok=bool(text), model=response.model, cost_usd=cost
        )
