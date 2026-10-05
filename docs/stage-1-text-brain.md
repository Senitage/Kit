# Stage 1: text brain

Kit can now chat by text in a browser or terminal, in character, with memory
that survives restarts. Hard questions go to Claude, and every Claude call's
cost goes in a spend log with a monthly cap. Settings can be changed from a
built-in page or `kit config`, with history and undo.

Finish [stage 0](stage-0-setup.md) first: `kit check` should pass for the data
folder, GPU, Ollama and Claude.

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
- **Claude for hard things:** say "ask Claude ..." to go straight to Claude, or
  Kit decides itself when a question is beyond the local model. Claude answers
  in Kit's voice. `kit memory spend` shows the month's spend. Kit stops asking
  Claude once `claude.monthly_cap_usd` is reached (default $20).
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
  Persona, models, the Claude cap and the brain's address are all there.
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

## 3. Run Kit as a service

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

## 4. Test before moving on

- [ ] **In character over 20 messages:** chat in the browser for 20 messages.
      Kit stays Kit: short replies, the persona's tone, sensible gestures.
- [ ] **Valid structured output:** run `kit eval`. It sends 50 prompts to the
      local model and needs `valid replies: 50/50`.
- [ ] **Claude:** "ask Claude why the sky is blue" and a genuinely hard
      question (for example "explain Kalman filters properly, with the maths")
      both come back from Claude, and both show in `kit memory spend`.
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
- **Claude says the budget is used up:** raise `claude.monthly_cap_usd`, or
  wait for the new month.
