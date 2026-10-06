# Stage 1: text brain

Kit can now chat by text in a browser or terminal, in character, with memory
that survives restarts. Small talk and quick things stay on the local model;
real questions, work and anything current (weather, prices, news) go to a cloud
model with web search. Which models do what, and how much stays local, are
settings you can change at any time. Every cloud call's cost goes in a spend log
with a monthly cap. Settings can be changed from a built-in page or
`kit config`, with history and undo.

Finish [stage 0](stage-0-setup.md) first: `kit check` should pass for the data
folder, GPU, Ollama and the cloud models.

## 1. Update and start Kit

In the Ubuntu terminal, in the Kit repo:

```
cd ~/kit
git pull
source .venv/bin/activate
pip install -e .
ollama pull nomic-embed-text    # lets Kit find memories by meaning (about 300 MB)
kit serve
```

Stage 0 already gave Ollama the settings that keep the chat and embedding models
loaded together on the 8 GB card (`sudo systemctl cat ollama` shows them).

`kit serve` prints two links with the API token on the end. Open the chat link
in a browser on the GPU PC's Windows side: WSL passes `127.0.0.1` through. The
page remembers the token, so after the first visit plain
`http://127.0.0.1:8600/` works. `kit token` shows the token again.

To open it from your phone or desk PC, run `kit config set brain.host 0.0.0.0`
and restart `kit serve`, then browse to `http://kit-server:8600/#token=...` over
Tailscale. Under WSL, Ubuntu's own network address is only reachable from this
PC, so `0.0.0.0` means "this PC and the tailnet", not the whole LAN. No Windows
firewall rule is needed.

## 2. What's new

- **Chat page** at `/`: replies stream in as they are written. Under each one
  you see the emotion and gestures Kit picked. The on-screen helper uses those
  names in stage 2, and the arm uses them later.
- **Terminal chat:** `kit chat` does the same thing without a browser.
- **Local and cloud, as one Kit:** the local model and the cloud models get
  the same persona, memories and conversation, and answer in the same format,
  so they sound like the same Kit. Cloud answers can carry written detail (code,
  steps, sources) that shows on screen but isn't spoken. See section 3 for
  choosing models. `kit memory spend` shows the month's spend, and Kit stops
  using cloud models once `cloud.monthly_cap_usd` is reached (default $40).
- **Memory** (how it works is in [memory.md](memory.md)):
  - Every turn, Kit searches what it knows for anything relevant to your
    message, by words and by meaning, and sees those memories with their
    dates. "Where's my tax stuff?" finds "tax returns are in
    Documents/Finance/Tax".
  - When you mention something it can't see, Kit searches deeper before
    answering, and says plainly when it doesn't know.
  - "Remember that ..." saves a fact straight away. If Kit already knows it, it
    doesn't save a copy; if it changes something ("I sold the Hilux"), the old
    fact is replaced and kept in its history.
  - At the end of each day Kit writes a summary of the day and learns its
    facts the same way. Old conversations are searchable too.
  - Pin a fact to keep it always in mind.
  - Memory is backed up to `backups/` every day; the newest 14 copies are kept.
- **Memory page** at `/memory`: see what Kit knows, grouped by kind (about
  you, preferences, projects, where things are, people, plans), search it the
  way Kit does, teach it something, and pin, edit or forget facts. The same
  from a terminal: `kit memory facts`, `search`, `remember`, `pin`, `forget`,
  `history`, `days`.
- **Settings page** at `/settings`: a form built from Kit's settings schema.
  Persona, routing, each model profile, the cloud budget and the brain's
  address are all there.
  Changes apply from the next message, with no restart. Every change keeps
  the previous version, and "Undo last change" steps back.
- **`kit config`** does the same from a terminal. It's the fallback when no
  browser or home_app is available:

  ```
  kit config show                     # settings in force
  kit config set persona.name Kit     # change one value
  kit config set persona.traits "['curious', 'dry humour']"
  kit config history                  # earlier versions
  kit config undo                     # back one change
  kit config reset                    # back to the defaults; undo brings yours back
  kit config check                    # is settings.toml valid?
  ```

- **Last good settings:** if settings.toml is broken by a hand edit, Kit keeps
  running on the last version that worked and says so on the settings page and
  in `kit config show`. Fix the file or save from the page to clear it.

## 3. Choose the models and how much stays local

`kit models` shows the model profiles, what each costs, and which one does what:

- **work** answers real questions and does the web searches (default `sonnet`,
  Claude Sonnet 5.5).
- **expert** takes the hardest problems (default `opus`, Claude Opus 5.5). The
  work model hands over to it when a question deserves it.
- The **local model** is `ollama.model` (qwen3:8b).

Built-in profiles are `sonnet`, `opus`, `gpt-sol` (OpenAI GPT-6.1 Sol) and
`gemini-flash` (Google Gemini 3.8 Flash). Switch with one command; it applies
from the next message:

```
kit models work gpt-sol                 # GPT does the work from now on
kit models expert sonnet                # no separate expert
kit config set models.sonnet.effort medium     # think harder (costs more)
kit config set models.gemini-flash.input_usd_per_mtok 1.5   # prices change
```

Each provider needs its own API key in the secrets folder, the same way as the
Anthropic key in stage 0: `openai_api_key` from platform.openai.com, or
`gemini_api_key` from aistudio.google.com (use a paid key: Google trains on
free-tier data). `kit check` tests the keys for the work and expert models.

How much stays local is `routing.mode`:

| Mode | Local model answers | Cloud answers |
| --- | --- | --- |
| `local-heavy` | everything it can | only what it can't do well |
| `balanced` (default) | small talk and quick commands | real questions, work, anything current |
| `cloud-first` | nothing, unless the cloud is down | everything |

```
kit config set routing.mode cloud-first
```

For one message, say "keep it local", "ask Claude" (or "ask GPT", "ask
Gemini", "ask the cloud", which all mean the work model), or "think hard" for
the expert. If the cloud can't be reached, or there's no key, or the budget is
used up, the local model answers instead and says why
(`routing.fallback_to_local`).

To compare models on real questions before switching, ask them the same ten
questions side by side. This spends real money, roughly 20 cents to a dollar a
model:

```
kit eval compare --models sonnet gpt-sol gemini-flash
```

It prints each model's time and cost, and writes the full answers side by side
to `state/evals/` in the data folder.

To try a bigger local model later (a 24 GB card), add a profile and point a
role at it:

```
kit config set models.big.provider ollama
kit config set models.big.model qwen3.8:27b
kit models work big
```

## 4. Run Kit as a service

Once you're happy with it, make Kit a systemd service, like Ollama. Stage 0's
`Kit WSL` scheduled task keeps Ubuntu running, so Kit starts when Ubuntu does
and restarts if it crashes. The same service file works unchanged on the Linux
server later.

```
sudo tee /etc/systemd/system/kit.service > /dev/null <<UNIT
[Unit]
Description=Kit
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=$USER
ExecStart=$HOME/kit/.venv/bin/kit serve
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now kit
systemctl status kit
```

`journalctl -u kit -f` shows what it's printing; `logs/kit.log` in the data
folder keeps the warnings and errors. After a `git pull` and `pip install -e .`,
run `sudo systemctl restart kit`.

## 5. Test before moving on

- [ ] **In character over 20 messages:** chat in the browser for 20 messages.
      Kit stays Kit: short replies, the persona's tone, sensible gestures.
- [ ] **Valid structured output:** run `kit eval`. It sends 50 prompts to the
      local model and needs `valid replies: 50/50`.
- [ ] **Balanced routing:** "morning" is answered locally; "what's the
      weather this afternoon?" and "explain Kalman filters properly, with the
      maths" go to the work model, the weather one with a web search. All
      cloud answers show in `kit memory spend`.
- [ ] **One message, your choice:** "ask Claude why the sky is blue" goes
      straight to the cloud; "think hard about ..." goes to the expert; "keep
      it local: ..." stays local.
- [ ] **Swap a model:** `kit models work opus`, ask a question, and the chat
      page shows Opus answered. Switch back with `kit models work sonnet`.
- [ ] **Cloud-first and back:** `kit config set routing.mode cloud-first`,
      and small talk now comes from the cloud. Set it back to `balanced`.
- [ ] **Offline:** with the internet unplugged (or the key file renamed),
      Kit says the cloud isn't available and answers locally.
- [ ] **Remembers yesterday:** tell Kit something ("remember my sister's
      birthday is 14 March"). Tomorrow, after restarting `kit serve`, ask about
      it in different words ("when's Emma's birthday?").
- [ ] **Memory is accurate:** run `kit eval memory`. It teaches a scratch
      memory 13 facts, some repeated and some changed, then asks 10 questions
      worded differently from the facts and 3 about things it was never told.
      It needs 10/10 recalled, 3/3 with nothing recalled, and a tidy memory
      (no stale or duplicate facts). Your real memory isn't touched.
- [ ] **Updates replace old facts:** tell Kit "remember I drive a Hilux", then
      later "I've swapped the Hilux for a Ranger". The memory page shows one
      fact about the Ranger, with the Hilux in its history.
- [ ] **Fast first words:** `kit eval` reports the time to first words. The
      median should be under a second once the model is warm.
- [ ] **Persona without restart:** change the persona on the settings page
      (try the name or the speech style). The next message uses it.
- [ ] **Bad values and undo:** `kit config set brain.port 0` is refused with a
      reason. Make a real change, then `kit config undo` restores the previous
      settings.
- [ ] **Broken file:** put a typo in settings.toml (for example delete a `]`).
      Restart `kit serve`: it starts on the last good version, prints a
      warning, and the settings page shows what's wrong.

If `kit eval` shows invalid replies or slow first words, try the fixes below,
then run it again.

## If something's off

- **First words take several seconds:** the first message after a while loads
  the model into the GPU. Kit asks Ollama to keep it loaded for 30 minutes. If
  every message is slow, check `ollama ps` shows `100% GPU`.
- **Replies are off-format:** check `ollama.think` is `false`, then try a lower
  `ollama.temperature` (0.4).
- **Kit sounds generic:** add more `persona.examples`. Small models copy
  examples much better than they follow descriptions.
- **Kit forgets its persona mid-conversation:** the context window is full.
  Raise `ollama.num_ctx` (8192 by default) or lower `brain.history_messages`.
- **Something went wrong overnight:** `logs/kit.log` in the data folder has
  the warnings and errors from `kit serve`.
- **`kit eval memory` misses things:** run `kit memory search "..."` with the
  question to see what Kit finds and how close each match is. If the right
  fact is there but below the cut-off, lower `memory.min_similarity` a little
  (try 0.45). If unknown questions recall unrelated facts, raise it.
- **Status says "words only":** the embedding model isn't answering. Check
  `ollama list` shows `nomic-embed-text`, then run `kit memory reindex`.
- **Kit says the cloud budget is used up:** raise `cloud.monthly_cap_usd`, or
  wait for the new month.
- **Too much goes to the cloud (or too little):** move `routing.mode` one step
  towards `local-heavy` (or `cloud-first`). In `balanced`, adding a persona
  rule such as "Answer questions about the time and date yourself" also helps.
