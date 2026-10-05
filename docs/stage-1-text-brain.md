# Stage 1: text brain

Kit can now chat by text in a browser or terminal, in character, with memory
that survives restarts. Hard questions go to Claude, and every Claude call's
cost goes in a spend log with a monthly cap. Settings can be changed from a
built-in page or `kit config`, with history and undo.

Finish [stage 0](stage-0-setup.md) first: `kit check` should pass for the data
folder, GPU, Ollama and Claude.

## 1. Update and start Kit

On the server, in the Kit repo:

```
git pull
.venv\Scripts\activate          # Linux: source .venv/bin/activate
pip install -e .
kit serve
```

`kit serve` prints two links with the API token on the end. Open the chat link
in a browser on the server. The page remembers the token, so after the first
visit plain `http://127.0.0.1:8600/` works. `kit token` shows the token again.

To open it from your phone or desk PC, set `brain.host` to `0.0.0.0`
(`kit config set brain.host 0.0.0.0`), restart `kit serve`, allow port 8600
through Windows Firewall for the private network, and browse to
`http://kit-server:8600/#token=...` over Tailscale.

## 2. What's new

- **Chat page** at `/`: replies stream in as they are written. Under each one
  you see the emotion and gestures Kit picked. The on-screen helper uses those
  names in stage 2, and the arm uses them later.
- **Terminal chat:** `kit chat` does the same thing without a browser.
- **Claude for hard things:** say "ask Claude ..." to go straight to Claude, or
  Kit decides itself when a question is beyond the local model. Claude answers
  in Kit's voice. `kit memory spend` shows the month's spend. Kit stops asking
  Claude once `claude.monthly_cap_usd` is reached (default $20).
- **Memory:** every message is kept in `state/memory.db`. When Kit runs into a
  new day, the local model turns yesterday's conversation into a few facts, and
  the newest facts go into every prompt. Telling Kit "remember that ..." saves
  a fact straight away. `kit memory facts` lists them, and `kit memory forget N`
  deletes one.
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
  kit config check                    # is settings.toml valid?
  ```

- **Last good settings:** if settings.toml is broken by a hand edit, Kit keeps
  running on the last version that worked and says so on the settings page and
  in `kit config show`. Fix the file or save from the page to clear it.

## 3. Run Kit at login (Windows)

Once you're happy with it, have Windows start `kit serve` at login:

1. Open **Task Scheduler** and choose **Create Task**.
2. General: name it `Kit`, select **Run whether user is logged on or not**.
3. Triggers: **At startup**.
4. Actions: **Start a program**. Program: the full path to `kit.exe` in the
   venv (for example `C:\Kit\.venv\Scripts\kit.exe`). Arguments: `serve`.
5. Settings: tick **If the task fails, restart every 1 minute**.

On Linux this becomes a systemd service in the server-move stage.

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
      it.
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
- **Claude says the budget is used up:** raise `claude.monthly_cap_usd`, or
  wait for the new month.
