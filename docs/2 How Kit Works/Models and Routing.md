---
tags: [how-it-works, topic/models]
aliases: [Routing, Local and cloud, Which model answers]
summary: Which model answers what - the local model, the cloud chat, work and expert roles, the routing modes, and the monthly budget.
related: ["[[Stage 1 - Text Brain]]", "[[Evals]]", "[[Inner Life In Depth]]"]
---

# Models and routing

> [!ABSTRACT] In short
> Kit has a **local model** on the server's GPU (free, private, quick) and
> **cloud models** for real work (Claude by default; GPT or Gemini if you
> like). Models fill **roles**: `chat` for everyday talk, `work` for real
> questions and web searches, `expert` for the hardest problems. A
> **routing mode** sets how much stays local. Whichever model answers, it gets
> the same persona, memories and conversation, and answers in the same shape,
> so it's always the same Kit.

## The roles

| Role | Default | Does |
|---|---|---|
| local | `ollama.model` (qwen3:8b out of the box) | Small talk in the local-leaning modes, anything you keep local, standing in when the cloud can't answer, finding memories by meaning |
| `chat` | `haiku` (Claude Haiku 5.5) | Everyday messages in cloud-only mode, about a twentieth of Sonnet's price |
| `work` | `sonnet` (Claude Sonnet 5.5) | Real questions, work, web searches, the end-of-day pass, key moments |
| `expert` | `opus` (Claude Opus 5.5) | The hardest problems, and his nightly reflection |

Built-in profiles are `sonnet`, `opus`, `haiku`, `gpt-sol` (OpenAI) and
`gemini-flash` (Google). Swap a role with one command, from the next message:
`kit models work gpt-sol`. Add your own profile, including a bigger local
one, under `[models]`. Each provider needs its own API key in the secrets
folder ([[Settings and Data#Secrets]]).

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

## The budget

Every cloud call's cost is logged (`kit memory spend`, `/api/spend`). Kit
stops using the cloud once the month reaches `cloud.monthly_cap_usd` ($40 by
default). As it runs low, calls give way in order, each step keeping
`cloud.reserve_usd` more in hand: evals and background work first, then fact
checks and key moments, then chat, so the nightly reflection always has the
last few dollars. If the cloud can't answer for any reason, the local model
answers and says why (`routing.fallback_to_local`).

## Weather and web search

Weather comes from a forecast service rather than a web search, and is usually
answered locally from the numbers. See [[Time and Weather]]. Claude can search
the web and open a page it found rather than trusting an old snippet.

## Try it

```
kit models                                   # which model does what, and prices
kit models work opus                         # swap a role
kit config set routing.mode cloud-first      # change how much stays local
kit eval compare --models sonnet gpt-sol     # the same questions, side by side
kit memory spend                             # this month's spend
```

## Go deeper
- [[Stage 1 - Text Brain#3. Choose the models and how much stays local]]: the full guide.
- [[Evals]]: comparing models properly.
- [[Inner Life In Depth#In conversation]]: what the local model is coached with.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/cloud.py`: Claude, GPT and Gemini behind one interface, the budget and skip order.
> - `src/kit/local_model.py`: the local model through Ollama.
> - `src/kit/settings.py`: `RoutingSettings`, `ModelProfile`, `CloudSettings`.
> - `src/kit/brain.py`: `route` and the hand-offs.
