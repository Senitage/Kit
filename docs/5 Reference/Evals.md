---
tags: [reference, evals, testing]
aliases: [kit eval, Eval suites, Measuring Kit]
summary: Kit's evals - repeatable checks of reply format and speed, memory recall, knowing where things live, cloud model comparisons, how alive he sounds, how good a companion he is, and reading your mood.
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
| `kit eval routing` | A scratch register of 8 things and 12 questions: does the right thing and place come back? Then your own questions against your real register | the embedding model | 12/12, plus yours |
| `kit eval compare --models A B` | The same questions to several cloud models, side by side in a file | the cloud (costs a little) | for reading |
| `kit eval voice --models A B` | Greetings, pipe-ups and private thoughts through each local model, with echo, canned-phrase and variety counts | local models | no echoes or canned lines; then read the file |
| `kit eval companion --models A B` | Goodbyes, hellos after four absences, wrong facts and news: does he act like a good companion? | local models | for reading |
| `kit eval mood` | Your labelled lines, read by meaning against the word rules | the model that would read them | reading by meaning only switches on once it beats the rules |

- Reports that are for reading go into `state/evals/` in the data folder;
  the path is printed at the end.
- Your own questions and lines live in the **config folder**, never the repo:
  `routing-questions.toml` for `routing`, `companion-lines.toml` for `mood`.
- `compare` is the only eval that spends: each call is logged with the rest of
  the cloud spend.

## When to run them

- **A new local model**: `replies`, then `voice` and `companion` with
  `--models` to read it next to the current one.
- **A new embedding model or `memory.min_similarity`**: `memory`, then
  `routing`.
- **A new cloud model**: `compare`.
- **A change to how he reads you**: `mood`.

## Go deeper
- [[Stage 1 - Text Brain]]: the replies, memory and routing evals in the stage 1 checklist.
- [[Side Stage - Inner Life]]: the voice bake-off.
- [[Companion Stage 1]]: the companion eval.

## Under the hood
- `src/kit/evals.py`: the prompts, scoring and reports.
- `src/kit/cli.py`: `kit eval` and its scratch memories.
