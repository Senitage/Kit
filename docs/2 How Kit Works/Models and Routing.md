---
tags: [how-it-works, topic/models]
aliases: [Routing, Local and cloud, Which model answers]
summary: Which model answers what - the local model, the cloud chat, work and expert roles, the routing modes, and the monthly budget.
related: ["[[Stage 1 - Text Brain]]", "[[Evals]]", "[[Inner Life In Depth]]"]
---

# Models and routing

> [!ABSTRACT] In short
> Kit has a **local model** on the server's GPU (free, private, quick) and
> **cloud models** for real work: Claude out of the box, any model you add.
> Models fill **roles**: `chat` for everyday talk, `work` for real
> questions and web searches, `expert` for the hardest problems. A
> **routing mode** sets how much stays local. What each model costs is
> **fetched daily** and shown in Australian dollars; the budget is in them too.
> Whichever model answers, it gets the same persona, memories and
> conversation, and answers in the same shape, so it's always the same Kit.

## The roles

| Role | Default | Does |
|---|---|---|
| local | `ollama.model` (qwen3:8b out of the box) | Small talk in the local-leaning modes, anything you keep local, standing in when the cloud can't answer, finding memories by meaning |
| `chat` | `haiku` (Claude Haiku 5.5) | Everyday messages in cloud-only mode, about a twentieth of Sonnet's price |
| `work` | `sonnet` (Claude Sonnet 5.5) | Real questions, work, web searches, the end-of-day pass, key moments |
| `expert` | `opus` (Claude Opus 5.5) | The hardest problems, and his nightly reflection |

## Your own list of models

A new Kit starts with three models, `haiku`, `sonnet` and `opus`, and that is
a starting list, not a set of presets: the models in your settings are the
ones you use. Add any model with one line, from Anthropic, OpenAI, Google or
Ollama, and take one out when you're done with it:

```
kit models add sonnet-6 --provider anthropic --model claude-sonnet-6
kit models work sonnet-6                 # a role switches from the next message
kit models remove opus                   # refused while a role still uses it
```

`kit models add` takes `--label`, `--effort`, `--max-tokens`, `--no-thinking`
and `--no-search`; anything not given takes the profile's default. A new model
nobody has a price for yet is said so at once (its calls count as free in the
budget until the price list has it). Each provider needs its own API key in
the secrets folder ([[Settings and Data#Secrets]]). Once the list differs
from the three starters, `settings.toml` holds it whole, under `[models]`.

A profile's `thinking` flag says whether the model thinks before it answers.
The built-in `haiku` profile has it **off**: everyday chat doesn't need it, and
the first words arrive sooner without thinking tokens ahead of them. Only
Claude Haiku takes the request (at `effort` up to `high`); Sonnet and Opus
always think, so for them the flag changes nothing. Turn it back on with
`thinking = true` under `[models.haiku]`.

## How much stays local

| `routing.mode` | Local model answers | Cloud answers |
|---|---|---|
| `local-heavy` | everything it can | only what it can't do well |
| `balanced` (default) | small talk and quick commands | real questions, work, anything current |
| `cloud-first` | nothing, unless the cloud is down | everything |
| `cloud-only` | only what you keep local, or if the cloud is down | the chat model takes everyday messages and hands real work to the work model |

For one message you choose: **"keep it local"** stays home, **"ask Claude"**
(or "ask GPT", "ask the cloud") goes to the work model, **"think hard"** goes
to the expert. When the work model thinks a question needs the expert, Kit
asks first ("that needs Opus, shall I ask it?") unless you turn
`routing.confirm_expert` off.

`routing.background` says who does Kit's own background work: his private
thoughts, his pipe-ups and comparing new facts with old ones. `local` keeps it
on the GPU; `chat` sends it to the cloud chat model (about A$2 a month), which
in cloud-only mode lets the local model leave the GPU so the voice has room.

> [!NOTE] How Dan runs Kit
> In October 2026 Dan's Kit runs `cloud-only` with `background = chat`, so
> Haiku chats, Sonnet works, Opus reflects, and the GPU is free for the voice.

## The moments that matter

Some answers are worth a better model even in a local-leaning mode:

- **Key moments** (`routing.key_moments`): bad news that lands hard, and his
  hello after a night or days away, are written by the work model, in Kit's
  voice and mood.
- **Fact checks** (`routing.check_facts`): "Sydney's the capital, isn't it?"
  is checked by the work model in the background while Kit gets ready, and he
  says the answer himself.
- **Nightly reflection**: the expert writes his journal and self-sheet. See
  [[Inner Life]].

Never for something you said to keep local.

## Prices, fetched for you

No price lives in Kit's settings, because a price typed in goes stale. Once a
day while he runs, Kit fetches the price list that LiteLLM keeps for every
model and the US dollar to Australian dollar rate from the European Central
Bank's feed, and keeps both in `prices.json` in the data folder. Every call is
costed at that day's prices and rate, in US dollars as billed and in
Australian dollars, and the spend log keeps the rate beside each call, so a
rate that moves later never rewrites the past. Until the first fetch, and on a
machine that can't reach the feeds, a table shipped with Kit stands in.

`kit models` shows every model's price per million tokens in Australian
dollars and where today's list and rate came from; `kit models prices`
fetches them now; `kit check` warns when the list is more than a week old or
a model in use has no price. Everywhere Kit shows money (`kit memory spend`,
the chat page, the desk app's reply details, home_app's Kit page), it's
Australian dollars.

## The budget

Every cloud call's cost is logged (`kit memory spend`, `/api/spend`). Kit
stops using the cloud once the month reaches `cloud.monthly_cap_aud` (A$60 by
default). As it runs low, calls give way in order, each step keeping
`cloud.reserve_aud` more in hand: evals and background work first, then fact
checks and key moments, then chat, so the nightly reflection always has the
last few dollars. If the cloud can't answer for any reason, the local model
answers and says why (`routing.fallback_to_local`).

## Caching

Claude charges a tenth of the price for the part of a prompt it has just read,
and starts answering sooner, as long as the new prompt begins exactly as the
last one did. So Kit lays every cloud request out stable-first:

1. the fixed instructions (who Kit is, his self-sheet, the actions), with a
   cache breakpoint at the end;
2. the conversation so far, with a breakpoint on Kit's last turn;
3. your new message, with this turn's part in front of it: the time, the
   memories he recalled, how he feels, the one line about your PC, the
   forecast and the list of your notes.

Only part 3 is new each turn; the rest is read from the cache. A list that
reorders itself (your notes, newest first) lives in part 3 for that reason.
The local model gets the same layout when it reads ahead
(`ollama.warm_up`), for the same reason.

You can see it working: `kit memory spend` shows `cached 1830/2400` beside
each call, the input tokens read from the cache over all of them. From the
second message of a conversation that should be most of the input.

## Weather and web search

Weather comes from a forecast service rather than a web search, and is usually
answered locally from the numbers. See [[Time and Weather]]. Claude can search
the web and open a page it found rather than trusting an old snippet.

## Try it

```
kit models                                   # which model does what, and today's prices
kit models work opus                         # swap a role
kit models add gpt --provider openai --model gpt-6.1-sol   # any model you like
kit models prices                            # fetch today's prices and rate now
kit config set routing.mode cloud-first      # change how much stays local
kit eval compare --models sonnet gpt         # the same questions, side by side
kit memory spend                             # this month's spend, in A$
```

## Go deeper
- [[Stage 1 - Text Brain#3. Choose the models and how much stays local]]: the full guide.
- [[Evals]]: comparing models properly.
- [[Inner Life In Depth#In conversation]]: what the local model is coached with.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/cloud.py`: Claude, GPT and Gemini behind one interface, the cache breakpoints (`system_blocks`, `cached_turns`), the budget and skip order.
> - `src/kit/local_model.py`: the local model through Ollama.
> - `src/kit/prices.py`: the price list and exchange rate, fetched daily, cached in the data folder, built in until then; what a call costs.
> - `src/kit/settings.py`: `RoutingSettings`, `ModelProfile`, `CloudSettings`.
> - `src/kit/brain.py`: `route` and the hand-offs.
