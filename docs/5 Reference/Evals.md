---
tags: [reference, topic/evals, topic/testing]
aliases: [kit eval, Eval suites, Measuring Kit]
summary: Kit's evals - repeatable checks of reply format and speed, memory recall, knowing where things live, cloud model comparisons, how alive he sounds, how good a companion he is, and reading your mood.
related: ["[[Stage 1 - Text Brain]]", "[[Side Stage - Inner Life]]", "[[Companion Stage 1]]"]
---

# Evals

Up: [[Home]] · Reference

> [!ABSTRACT] In short
> Unit tests (`pytest`) prove the code does what it says. **Evals** check
> what tests can't: how the real models behave. Each `kit eval` runs a fixed
> set of messages through Kit and scores or writes out the results, so a new
> model or a prompt change can be judged by numbers and by reading, not by
> feel. Most run on a **scratch memory** and never touch Kit's real one.

| Eval | What it checks | Runs on | Passing looks like |
|---|---|---|---|
| `kit eval` (`replies`) | 50 prompts: every local reply comes back in Kit's shape, and how fast the first words arrive | the local model | 50/50 valid; median first words under a second, warm |
| `kit eval memory` | Teaches a scratch memory 13 facts (some repeated or changed), then asks 10 questions in other words and 3 about things never told | the embedding model | 10/10 recalled, 3/3 nothing, a tidy memory; suggests `memory.min_similarity` |
| `kit eval memory --replay SNAPSHOT` | Your own questions (`memory-questions.toml`) against a copy of a real memory snapshot, usually a backup: does the right fact still come first after months of recalls and changes? `--questions FILE` for another file | the embedding model, your memory (a copy) | every expected fact first; `LOW` says where it came, `MISS` that it wasn't recalled |
| `kit eval tools` | Each pack's questions, plus yours: does the message load the right pack, and is the right tool called with the right arguments? See [[#kit eval tools]] | offline: matching only; `--live`: the chat model | offline every case; live, at most one miss in ten |
| `kit eval routing` | A scratch register of 8 things and 12 questions: does the right thing and place come back? Then your own questions against your real register | the embedding model | 12/12, plus yours |
| `kit eval compare --models A B` | The same questions to several cloud models, side by side in a file | the cloud (costs a little) | for reading |
| `kit eval voice --models A B` | Greetings, pipe-ups and private thoughts through each local model, with echo, canned-phrase and variety counts | local models | no echoes or canned lines; then read the file |
| `kit eval companion --models A B` | Goodbyes, hellos after four absences, wrong facts and news: does he act like a good companion? | local models | for reading |
| `kit eval mood` | Your labelled lines, read by meaning against the word rules | the model that would read them | reading by meaning only switches on once it beats the rules |

- Reports that are for reading go into `state/evals/` in the data folder;
  the path is printed at the end.
- Your own questions and lines live in the **config folder**, never the repo:
  `routing-questions.toml` for `routing`, `memory-questions.toml` for `memory
  --replay`, `companion-lines.toml` for `mood`, `tool-questions.toml` for
  `tools`.
- `memory --replay` copies the snapshot into a scratch folder and asks there,
  so neither the backup nor the live memory is written to. Items the snapshot
  has no vectors for (another embedding model) are embedded first. Each
  question is `ask = "..."` and `expect = "..."`, words the right fact
  contains; `tests/replay/memory-questions.toml` is an example.
- `compare` and `tools --live` are the evals that spend: each call is logged
  with the rest of the cloud spend.

## kit eval tools

Each pack brings its own questions, each with the tool a good answer calls
first (or none, for "Morning!") and the arguments it should carry. An
argument matches when the call has it and its value contains the expected
one, ignoring case, so `place = "Richmond"` matches `"Richmond, NSW"`.

- **Offline** (the default, no model, free): the message goes through pack
  matching, and the expected tool must be on offer from the loaded packs
  with arguments its schema takes. A question that needs no tool passes when
  no extra pack loads. This catches a pack whose words or questions don't
  find it, and arguments that drifted from the tool.
- **`--live`**: the real chat model answers each question with every tool
  stubbed ("(stubbed in the eval)"), so nothing real happens, and the first
  call it makes is compared. It runs in a scratch memory; its spend is added
  to the real log so it counts toward the cap. One miss in ten passes.

Your own questions go in `tool-questions.toml` in the config folder:

```toml
[[case]]
question = "Will it rain on Saturday?"
tool = "weather"
pack = "core"
arguments = { place = "" }

[[case]]
question = "Thanks mate"   # no tool: leave tool out
```

## When to run them

- **A new local model**: `replies`, then `voice` and `companion` with
  `--models` to read it next to the current one.
- **A new embedding model or `memory.min_similarity`**: `memory`, then
  `routing`.
- **A change to recall or its weighting, or now and then**: `memory
  --replay` on last night's backup, to catch ranking drift.
- **A new cloud model**: `compare`.
- **A change to how he reads you**: `mood`.

## Go deeper
- [[Stage 1 - Text Brain]]: the replies, memory and routing evals in the stage 1 checklist.
- [[Side Stage - Inner Life]]: the voice bake-off.
- [[Companion Stage 1]]: the companion eval.
- [[Tools and Packs]]: what the tools eval tests.

## Under the hood
- `src/kit/evals.py`: the prompts, scoring and reports.
- `src/kit/evals_cli.py`: `kit eval` and its scratch memories (`src/kit/cli.py` hands it the command).
