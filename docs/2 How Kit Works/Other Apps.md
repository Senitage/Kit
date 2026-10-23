---
tags: [how-it-works, topic/apps, topic/home-app, topic/mettools, topic/tools]
aliases: [home_app, MetTools, Configurators, Apps as packs, MCP]
summary: How Kit fits with Dan's other apps - home_app shows and configures Kit, any app with an MCP server becomes a pack of his tools, Home Assistant is the house - and the one rule, that Kit never depends on any of them.
related: ["[[API]]", "[[Roadmap]]", "[[Privacy]]", "[[The House]]", "[[Tools and Packs]]", "[[Stage 4 - Tools]]"]
---

# Other apps

> [!ABSTRACT] In short
> Kit stands on his own. Other apps can **show and configure** him by calling
> his API, and any app with an **MCP server** becomes a **pack of his tools**:
> list one under `apps.servers` and its tools load when a message is about
> it. A tool that changes something asks first. If an app is down he says
> it's out of reach and carries on; he never needs one to run.

```mermaid
flowchart LR
    Home["home_app (the home website)"] -- "calls Kit's API with a token" --> Kit["Kit's brain"]
    Kit -- "MCP: its tools as a pack" --> Met["MetTools"]
    Kit -- "MCP: its tools as a pack" --> Home
    Kit -- "WebSocket, non-admin" --> HA["Home Assistant"]
```

## The rule

**Kit never depends on home_app**, or on any other app. Apps that configure
Kit call him; when Kit uses an app's tools it's an extra he can do without.
His settings live in his own data folder and have their own page,
`kit config` and the desk app, so nothing else has to be up for him to be
himself. See [[Settings and Data]].

## Apps as packs

An app joins Kit in three steps:

1. **It runs an MCP server.** The Model Context Protocol is a small, shared
   way for an app to list its tools and run them. Kit is the client. It
   reaches the server over **HTTP** (the server's address, for an app on
   another machine) or starts it as a **program** on the same box and talks
   to it line by line.
2. **It gets a line in Kit's settings**, under `apps.servers.<name>`: its
   `url` or `command`, the name of its token file in the secrets folder
   (`token_secret`), and the `words` and `questions` that should load it,
   since a server can't say those. See [[Settings Reference#apps]].
3. **Optionally, a `contents` tool.** Once a day Kit asks for the app's saved
   work as rows (`{"kind", "ref", "text", ...}`) and keeps them in his memory
   as the `app:<name>` source. So "my last pump calc" is found by meaning,
   and the [[Register of Things]] can link to it.

Then restart Kit. `kit check` gets a line per app: connected, and how many
tools it has.

### What becomes of its tools

Each tool the server lists becomes one of Kit's, named after the app
(`mettools_run_calculation`), with the server's own description and
arguments. What it does to your world comes from the tool's own labels
(its **annotations**):

| The server says | Kit treats it as | Asks first? |
|---|---|---|
| Read-only | a look | No |
| Not destructive | an action | No |
| Destructive, or says nothing | a change | Yes, every time |
| Named in the app's `confirm` | as above | Yes |

A tool that says nothing about itself asks, because by the protocol's own
rules it may change things. The app adds the labels when it's ready.

Two tools of Kit's own join every app's pack:

- `<app>_status` says whether the app can be reached and what he can do in
  it. While it's down this is the only one offered, so he says "MetTools is
  out of reach right now" instead of guessing.
- `<app>_find` searches the app's saved work in his memory, once there is
  some.

A text answer comes back as it is (cut at about 8,000 characters). A
picture or a file is described ("an image, image/png, 120 kB"), never passed
on. A **private** app's answers reach a cloud model only as the local
model's short summary, like a private folder's. See [[Privacy]].

### When an app goes away

He lists each app's tools again every `apps.relist_minutes` (60), and at
once when the server says they changed. If an app stops answering, its tools
drop out and he tries again: after 5 seconds, then 10, 20 and so on, up to
every five minutes. Nothing else about him changes.

### From the phone

On the phone he tells you things rather than opening them. If you ask him to
open something, it opens on the PC, and he says it happened there.

## home_app

The home website (Django, on the NAS) has a **Kit section**:

| Page | What's on it |
|---|---|
| Health | His face, how he's feeling and his needs, a chat box, and what the cloud has cost this month |
| Settings | All of Kit's settings, drawn from his settings schema, so new settings show up by themselves |
| Memories | What he remembers: search, pin, edit and forget |

![[home-app-panel.jpg|420]]

- home_app talks to Kit **from its server**, with Kit's token from
  `kit token`. The token never reaches the browser.
- Chat from home_app uses the `home` channel, so Kit knows where you're
  talking from. See [[Brain#Where you're talking from]].
- His face is drawn from the same character sheet as the desk. For Kit 3D,
  home_app passes the brain's face page through, so it's the same live 3D
  face. See [[Face]].
- The Kit pages are for people given `view_kit` or `control_kit` in
  home_app, since memories are private.
- home_app also has an MCP server (trips, vehicles, bills, fuel), which Kit
  uses as the `home_app` pack, marked private. Its labels and `contents`
  rows come in part F3.

## MetTools

Dan's engineering calculators. MetTools has its own MCP server (in its repo,
`kit_mcp/server.py`), which Kit starts as a program on his box and uses as the
`mettools` pack. Through it he can:

| What | How it works | Asks first? |
|---|---|---|
| **Find saved work** | Saved calcs, projects, estimates, mass balances, documents and equipment, read from MetTools. Once a day they're also kept as the `app:mettools` source, so "my last tails pump calc" is found by meaning | No |
| **Open a calculation** | Gets the save's address and opens it on your PC | No |
| **Run a calculator** | The app's own engines, with no browser: from the defaults, or a variation on a save ("what if it's 40% solids?") | No |
| **Save a result** | Files it as a new draft, never over an old one | Yes |
| **Work on the page you have open** | Reads the page, fills fields, runs it, opens other tools, puts a note in the corner. Only listed while MetTools is open in your browser | Saving does |

He reads the results MetTools gives back rather than doing the sums himself.
Every calculator but the bulk conveyor (held back for a redesign) runs
without a browser. Which tools ask first is MetTools' own call: its tools say
what they do, and its admin page has a list of extra ones to confirm.

### Setting it up

MetTools' server runs **next to Kit**, not inside MetTools, and talks to
MetTools' Kit API with a token of its own. Kit hands it two things when he
starts it: the token from his secrets folder (as `KIT_APP_TOKEN`) and
MetTools' address (from `env`). The calculators need Node.js 18 or newer on
the box. The steps are in [[Stage 4 - Tools#Part F2: MetTools in full]].

## Home Assistant

Kit connects to Home Assistant over its WebSocket API as his own non-admin
user, to see and switch what you expose to Assist, with locks, alarms and
the garage confirmed first. If it's down he says the house is out of reach
and carries on. See [[The House]].

## Try it

```toml
[apps.servers.mettools]
command = ["/home/kit/METTOOLS/.venv/bin/python", "/home/kit/METTOOLS/kit_mcp/server.py"]
env = { METTOOLS_URL = "http://192.168.1.50:8000/tools" }
token_secret = "mettools_token"
words = ["pump", "slurry", "calc", "estimate", "mass balance", "MetTools"]
```

Restart Kit, run `kit check`, then ask him: "what's in MetTools?"

## Go deeper
- [[API]]: the endpoints home_app uses.
- [[Tools and Packs]]: packs, offering and asking first.
- [[Stage 4 - Tools]]: parts F1 and F2, setup and test checklists.
- [[Privacy]]: tokens, and what stays local.
- [[The House]]: Home Assistant, the house pack and what he notices.

> [!under-the-hood]- Under the hood: the code
> - `src/kit/mcp_client.py`: the small MCP client, over HTTP or a program's
>   input and output.
> - `src/kit/tools/mcp.py`: `App` (the connection, listing, reconnecting)
>   and its pack, and `write_contents` for the saved work.
> - `src/kit/checks.py`: the `app:` lines of `kit check`.
> - `src/kit/routes/`: the API other apps call, one file per part of Kit.
> - `src/kit/channels.py`: the `home` and `phone` channels.
> - `src/kit/settings.py`, `src/kit/settings_store.py`: the settings, their schema, and changes with undo.
