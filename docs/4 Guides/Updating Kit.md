---
tags: [guide, topic/updating]
aliases: [Update Kit, Testing a pull request, Restart Kit]
summary: How to update the server to the latest Kit, try a pull request before it's merged and go back afterwards, and update the desk app and the eyes.
---

# Updating Kit

Up: [[Home]] · Guides

> [!ABSTRACT] In short
> The server runs `main`. To update: pull, reinstall, restart. To try a pull
> request first: back up memory, check its branch out, restart, and go back to
> `main` when you're done. The desk app updates itself; the eyes are a pull on
> the PC.

## Update the server

In the Ubuntu terminal on the server:

```
cd ~/Kit
git checkout main
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
kit check
```

- Memory upgrades itself when Kit starts, if a new version needs it, and a
  backup is taken every day anyway.
- Settings carry over. A new setting starts at its default; see what's new
  with `kit config show` or the settings page.
- A stage guide says if anything else is needed (a new package, model or key).

### Settings from an older Kit

From October 2026 `settings.toml` holds only what you changed
([[Settings Reference#What the file holds]]). An older file held every value,
so a price or a persona line that moved in the code never reached it. The
first start after this update reads the old file, keeps what you had changed,
drops the rest and rewrites it as `schema_version = 2`. Two things to check
afterwards:

- `kit models` now shows the current model ids and today's prices. A profile
  of your own (one you added under `[models]`) is kept exactly as it was.

From mid October 2026 (version 3) the models are **your own list** and
**prices aren't settings**: the first start keeps the models a role uses and
any you had changed or added, drops the rest (`gpt-sol` and `gemini-flash`
went unless you used them; `kit models add` brings one back), takes the
prices out, and turns `cloud.monthly_cap_usd` and `reserve_usd` into
`monthly_cap_aud` and `reserve_aud` at about A$1.50 to the dollar. Earlier
calls in the spend log are converted at the same rate once. Run `kit models`
to see the list and where today's prices came from, and `kit models prices`
to fetch them straight away. home_app's Kit page shows Australian dollars from
its matching update.
- `persona.knows` used to start with a line of the author's own life; the
  built-in line now says Kit is still getting to know you. If yours was the
  built-in one, Kit no longer knows those things from his settings (his memory
  is untouched). Put your own in:
  `kit config set persona.knows "Lives in Richmond with ..."`, or on the
  settings page.

### After the notes pack update

The first notes sync after stage 4 part E1 reads every note in the vault once
more, to pick up its tasks, tags and links. On a big vault on the NAS that
first sync takes a little longer; after it, only changed notes are read.

## Try a pull request before it's merged

```
cd ~/Kit
kit memory backup                       # a copy to come back to
git fetch
git checkout BRANCH-NAME                # the pull request's branch
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart kit
```

Then work through the checklist in that pull request's guide. To go back:

```
git checkout main
pip install -e .
sudo systemctl restart kit
```

If the branch upgraded memory and `main` doesn't like it, stop Kit, copy the
backup from `backups/` over `state/memory.db` in the data folder, and start it
again. See [[Settings and Data#The data folder]].

> [!TIP] Two branches at once
> To try two unmerged branches together, make a local branch from one and
> merge the other in (`git checkout -B try-both origin/BRANCH-A`, then
> `git merge origin/BRANCH-B`). Merge, never rebase.

## The desk app

It checks GitHub for a new release about a minute and a half after it starts,
then daily, and asks before installing. **Check for updates** in the tray
menu checks now. A pull request's **test build** comes from that pull
request's "Desk app" check; skip the Update offer while you test it, or it
swaps back to the latest release. See [[Desk App Builds and Updates]].

## The eyes

On the desk PC, `git pull` in the eyes' copy of Kit, `pip install -e ".[eyes]"`
if the guide says there's something new, then stop and start `kit eyes`. Their
settings come from the brain, so there's nothing else to change. See
[[Vision Stage 1]].
To run them without the GPU, see [[Eyes#Without a graphics card]]: it's one
`pip install` and a few settings.

## The ears

The same on the PC with the mic: `git pull` in that copy of Kit,
`pip install -e ".[hearing]"` if the guide says there's something new, then
stop and start `kit hearing`. See [[Companion Stage 5]].

A setting saved in your settings file keeps its value when an update changes
the default. So if `hearing.names` is already there, add any new spellings of
his name yourself (`kit config show` lists what's set).

## The voice engine

Chatterbox has its own Python (`speech.engines.*.python`), which Kit updates
never touch. A stage guide says when it needs something new. See
[[Stage 3 - Voice]].

## The voice program

On the PC with the graphics card (in WSL), `git pull` in that copy of Kit,
`pip install -e .` in its `.venv`, then `sudo systemctl restart kit-voice`.
Kit sends it the engine's settings and his voice clip itself, so there's
nothing else to change there. See
[[Stage 3 - Voice#His voice on another computer]].

## If something's off

- `kit check` says what's wrong with the setup.
- `journalctl -u kit -n 100` shows why the service stopped.
- The log is `logs/kit.log` in the data folder; the voice's is
  `logs/speech.log`.
- `kit config undo` takes back the last settings change.
