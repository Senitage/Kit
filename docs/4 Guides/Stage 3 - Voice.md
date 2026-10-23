---
tags: [guide, stage, topic/voice]
aliases: [stage-3-voice]
summary: Stage 3 part 1, Kit's voice - setting up each engine, changing his voice, moving to another machine, his voice on another computer's graphics card, and the test checklist.
---

# Stage 3, part 1: Kit's voice

Up: [[Home]] · Guides · [[Voice]]

Kit speaks his replies through the desk PC's speakers. Hearing (microphone, wake
word, speech to text) is the next part of stage 3.

## How it works

- **Swappable engines.** Each voice engine is a profile under `[speech.engines]`
  in the settings, like the model profiles. Built in:

  | Profile | Engine | Runs on | Mood |
  | --- | --- | --- | --- |
  | `kokoro` | Kokoro, voice `af_heart` | processor | speed |
  | `piper` | Piper, `en_US-lessac-medium` | processor | speed |
  | `chatterbox` | Chatterbox, copies `kit_voice.wav` | graphics card | emotion dial |
  | `chatterbox-turbo` | Chatterbox Turbo, copies `kit_voice.wav` | graphics card | an opening sound ([sigh], [chuckle]) |
  | `tone` | beeps, one per word | processor | for testing |

  Add your own the same way, for example a second Kokoro voice:
  `kit config set speech.engines.bella.kind kokoro`, then
  `kit config set speech.engines.bella.voice af_bella`.

- **Each engine runs as its own background program** (`src/kit/speech/worker.py`),
  started by Kit's server with whichever Python has that engine installed. Chatterbox
  and Kokoro need different numpy versions, so they can live in separate virtual
  environments. Switching engines stops the old program, which frees the graphics
  card memory it held.
- **Sentence by sentence.** The brain now sends Kit's mood before his words. The
  desk app cuts the words into sentences as they stream in, asks the server for
  each one, and plays it while the next is being made. The first sentence is cut
  short where it can be, at its first comma after at least four words ("Yeah, I
  had a look at that,") or before an "and" or "but", because Chatterbox makes a
  whole piece before any of it plays. So Kit starts talking a few words after the
  brain does, not after the whole reply. A one-word "Yeah," is never cut off on
  its own: it sounded like a stammer.
- **Each sentence comes in pieces.** On the graph path Turbo's sounds are turned
  into audio a second at a time and each piece streams through the server to
  the desk (`audio/L16`), which plays it while the rest is still being made. A
  long sentence starts a second into its making, and a short sentence followed
  by a long one leaves no hole. His mouth follows the sound itself, measured on
  the desk as it plays. See [[Voice#How a sentence becomes sound]].
- **Interrupting him starts the new reply at once.** Each sentence carries its
  reply's generation number, so the server drops leftovers of the reply you cut
  off instead of making them, and the desk doesn't wait for a sentence still
  being fetched. While the engine is loading, the server says "not yet" (503)
  straight away instead of holding the request for minutes. See
  [[Voice#How a sentence becomes sound]].
- **Timing in the log.** Each reply leaves three lines in the server log
  (`journalctl -u kit`): when his first words came, when the reply was done, and
  how long his first sound took to make, all counted from Dan's message.
- **His last sentence doesn't wait.** The brain says `spoken` as soon as Kit's
  words are complete (a blank line, or three sentences), while the local model is
  still writing any detail for the screen. His voice used to wait about two
  seconds for that.
- **One steady sound output.** The desk app keeps one sound output open while Kit
  talks (PortAudio, from the `sounddevice` package), and opens it while he's still
  thinking. Sentences follow each other with no gaps, and his first word isn't
  clipped: playing each sentence on its own woke the speakers every time, and
  waking them lost the first letters. If that output won't open, the desk app
  falls back to playing each sentence on its own, with a moment of silence first.
- **His words show as he says them.** With his voice on, each sentence appears in
  the chat as he starts saying it, and his face acts the reply out as his voice
  starts. Turn it off on the Look page ("Show Kit's words as he says them"). If his
  voice fails or goes quiet, the words show anyway.
- **Pipe-ups are said too.** A line Kit comes out with by himself is spoken, unless
  he's already talking.
- **Mood.** Kit's emotion sets `exaggeration` for Chatterbox (per emotion, in
  `speech.engines.chatterbox.exaggeration`), an opening sound for Turbo
  (`mood_tags`), and a small speed change for Kokoro and Piper (`mood_speed`).
- **Dan talking stops Kit.** Sending a message stops Kit straight away, mid-word,
  and drops whatever he hadn't said yet. The rest of his words still show above
  Dan's message.
- **Reading ahead (optional).** `kit config set ollama.warm_up true` has the local
  model read the conversation in after each reply, once Kit's voice has finished,
  so the next message only has itself left to read. Gemma models re-read the whole
  prompt whenever anything in it changes, which took about two seconds a message.
  With it on, what changes every message (the time, what Kit recalled, the PC)
  goes beside Dan's message rather than in Kit's instructions. Off by default
  while it's tried, and never in cloud-only routing, where the local model only
  stands in and reading ahead would just load it back onto the GPU.
- **Speech off** (`kit speech off`) stops the engine within a few seconds, which
  frees its memory. With speech on, the server loads the engine at start-up, so
  the first reply isn't kept waiting.

## Set it up on the server

1. Update and restart Kit as in [[Updating Kit]], and let the desk app
   update: the new build brings the `sounddevice` package it plays sound with
   (see [[Desk App Builds and Updates#Updates|the desk app guide]]).
2. **Kokoro** in Kit's own Python: `pip install kokoro-onnx`. Its model files
   download into `<data>/state/speech/models` the first time.
3. **Chatterbox** in its own Python 3.11 environment. `~/kit-voice/.venv` from the
   auditions already has it; point both Chatterbox profiles at it:

   ```
   kit config set speech.engines.chatterbox-turbo.python ~/kit-voice/.venv/bin/python
   kit config set speech.engines.chatterbox.python ~/kit-voice/.venv/bin/python
   ```

   A fresh one: `uv venv -p 3.11 ~/kit-voice/.venv`, then
   `uv pip install -p ~/kit-voice/.venv/bin/python chatterbox-tts "setuptools<81"`
   (setuptools still carries `pkg_resources`, which the Perth watermarker
   Chatterbox imports on start-up needs; Kit doesn't run the watermark, see
   [[Voice#Faster on a graphics card]]).
4. **Kit's voice clip.** Copy Heart's reference clip into the data folder (`kit paths`
   shows where it is), as `<data>/state/speech/kit_voice.wav`, or set
   `speech.engines.chatterbox-turbo.reference` to the clip's full path.
   Any clip of 6 seconds or more works; without one, Chatterbox uses its own voice.
5. **Piper** (optional): in Kit's Python, `pip install piper-tts`, then
   `python -m piper.download_voices en_US-lessac-medium --data-dir <data>/state/speech/models`.
6. Pick the engine and turn speech on:

   ```
   kit speech use chatterbox-turbo
   kit speech on
   ```

## Changing his voice

Chatterbox copies whatever voice is in its reference clip; it has no list of
voices of its own. Any clear recording of one person talking, 6 to 20 seconds
long, with no music or background noise, works as a `.wav`.

1. Copy the clip into `<data>/state/speech/` under its own name, so the old one
   stays. From WSL, Windows' C: drive is `/mnt/c`, for example
   `cp /mnt/c/Users/<you>/Downloads/new_voice.wav <data>/state/speech/`.
2. Point the engine at it: `kit config set speech.engines.chatterbox-turbo.reference new_voice.wav`.
   A name on its own is looked for in `<data>/state/speech/`; a full path works too.
   Kit restarts the engine itself when this changes.
3. Listen: `kit speech say "Hey, how do I sound now?"`.

To keep several voices to flip between, give each its own profile, then switch
with `kit speech use`:

```
kit config set speech.engines.voice2.kind chatterbox-turbo
kit config set speech.engines.voice2.python ~/kit-voice/.venv/bin/python
kit config set speech.engines.voice2.reference new_voice.wav
kit speech use voice2
```

## Moving Kit to another machine

What lives where:

- **Kit's code and its own Python** (the repo and its `.venv`): reinstall from git.
- **Kit's data folder** (`kit paths`): settings, memory and the voice clips under
  `state/speech/`. Copy it across whole.
- **The Chatterbox Python** (`~/kit-voice/.venv` here): not part of Kit, so it
  doesn't move with the data folder. Make a fresh one as in step 3 above, then
  point `speech.engines.<name>.python` at it again for every Chatterbox profile.
- **Kokoro and Piper model files** sit in `<data>/state/speech/models`, so they
  come with the data folder; reinstall `kokoro-onnx` or `piper-tts` into Kit's Python.

Then `kit speech use <name>`, `kit speech on`, and `kit speech say` to check.

If the new machine has no graphics card, his Chatterbox voice can stay on the
old one's: see the next section.

## His voice on another computer

Kit on a server with no graphics card can still speak with Chatterbox Turbo on
the PC's card: the **voice program** runs on the PC and dials in to Kit (see
[[Voice#His voice from another computer]]). Nothing on the PC listens on the
network, so there's no port forward or firewall rule to add.

On the PC, in WSL:

1. **Only the voice program runs here, never Kit's server.** If an old copy of
   Kit ran here, `systemctl is-enabled kit` must say `disabled`: two Kits on
   one data folder split his memories.
2. Update Kit's code: `git pull` in the WSL copy of Kit, then
   `pip install -e .` in its `.venv`. The voice program is part of Kit, so it
   runs with Kit's Python; the engine still runs with the Chatterbox Python
   (`~/kit-voice/.venv` from the steps above).
3. Tell it where Kit is, with the token from `kit token` on the server:

   ```
   kit voice connect http://kit-server:8600 TOKEN
   ```

   That's saved in `~/.config/kit-voice` (the token in a file of its own). It
   never reads a Kit data folder on the PC, which may be an old copy.
4. Try it in the foreground:

   ```
   kit voice --python ~/kit-voice/.venv/bin/python
   ```

   It says it's connected, then loads the engine once Kit asks for it (next
   steps). Ctrl+C stops it. `--python` is the Python with Chatterbox
   installed here; without it, the engine profile's `python` setting is used.

On the server:

5. Mark the engine as made on the other computer, keep a voice on the server
   to fall back on, and switch to it:

   ```
   kit config set speech.engines.chatterbox-turbo.remote true
   kit config set speech.fallback kokoro
   kit speech use chatterbox-turbo
   kit speech on
   ```

   His voice clip stays where it is, in the server's data folder
   (`<data>/state/speech/`). Kit sends it to the voice program with the
   engine's settings, which saves it in its own folder.
6. `kit speech` shows the link at the bottom: the PC's name, `ready`, `cuda`
   and the CUDA graph on. `kit speech say "Hello from the PC"` goes through
   the server, so it shows the first sound as the desk hears it.

Back on the PC, run it as a service so it starts with WSL (the logon task
from [[Stage 0 - Server Setup]] keeps WSL running). Make
`/etc/systemd/system/kit-voice.service`, with your user and paths:

```ini
[Unit]
Description=Kit's voice on this PC's graphics card
After=network-online.target
Wants=network-online.target

[Service]
User=you
ExecStart=/home/you/Kit/.venv/bin/kit voice --python /home/you/kit-voice/.venv/bin/python
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl daemon-reload` and `sudo systemctl enable --now kit-voice`.
`journalctl -u kit-voice -f` shows it connecting and each sentence's timing.
The engine's own messages go to `~/.config/kit-voice/logs/speech.log`.

## Commands

- `kit speech`: the engines, which one is in use, and whether speech is on.
- `kit speech use <name>`: switch engine; the server loads it in the background.
- `kit speech on` / `kit speech off`.
- `kit speech say "Oh, nice! Told you it would." --engine kokoro --mood happy`: say
  a line, print how long each sentence took, and save it under
  `<data>/state/speech/said`.
- `kit speech bench --engines chatterbox-turbo kokoro piper`: the same six Kit
  lines (six moods) through each engine. It prints when each starts talking, how
  much faster than real time it is, whether speech has gaps, and graphics card
  memory, and writes a page to listen and compare under
  `<data>/state/speech/bench/<time>/index.html`.

`say` and `bench` start their own copy of the engine on the next port up, so they
don't disturb the server. With Chatterbox loaded by the server too, that's two
copies on the graphics card: run `kit speech off` first if memory is tight.

The engine's own messages go to `<data>/logs/speech.log`.

## Test checklist

- [ ] `kit speech` lists the five engines, with `kokoro` in use.
- [ ] `kit speech say "Oh, nice! The flotation model finally behaved." --engine kokoro --mood happy`
      prints two lines with timings and saves a WAV that sounds right.
- [ ] The same with `--engine chatterbox-turbo` speaks in Heart's voice. The first
      line takes about a second.
- [ ] `kit speech bench --engines chatterbox-turbo kokoro` writes the compare page;
      Turbo "keeps up".
- [ ] With Turbo on the graphics card, `GET /api/speech` shows `cuda_graph: true`,
      and `<data>/logs/speech.log` has no "no CUDA graph" line. Turbo is well
      over twice as fast as real time in the bench.
- [ ] `kit speech use chatterbox-turbo` and `kit speech on`, then in the desk app's
      chat, ask something. Kit starts speaking after his first sentence and the
      rest follows without gaps.
- [ ] The first word of each reply is whole: no missing first letters.
- [ ] A one-sentence reply starts speaking about a second after its words would
      have shown, and the words appear as he says them.
- [ ] Ask something, then send a new message while he's talking: he stops at
      once, and the rest of what he was saying shows above your message. His
      new reply's first sound comes within about half a second of its first
      words, not after the old sentence the engine was on.
- [ ] A reply opening "Yeah, I had a look at that yesterday" is spoken as one
      piece up to the next comma, not "Yeah," on its own.
- [ ] `kit speech use chatterbox-turbo` while speech is on and Chatterbox is
      not loaded: ask something at once. The words show unvoiced within a few
      seconds (the server log shows `503`), a later reply is voiced, and nothing
      waits for minutes.
- [ ] With "Boop when Kit talks" on and his voice on, replies have no boop over
      his first word; with his voice off, the boop is back.
- [ ] In `<data>/logs/kit.log`, "first sound made in" for a short first sentence
      is under what it was before (about 0.8 s on an RTX 2070 Super): no
      watermark, and the speaker conditioning worked out once.
- [ ] When Kit pipes up by himself, he says it out loud.
- [ ] Untick "Show Kit's words as he says them" on the Look page: words appear as
      they stream in again, and he still speaks.
- [ ] With routing other than cloud-only, `kit config set ollama.warm_up true`,
      then chat for a few turns. In `<data>/logs/kit.log`, each message's first
      `local model: read N tokens` line drops from thousands of tokens to a few
      hundred from the second message on, and replies start sooner.
- [ ] Ask something that makes him grumpy or tired: some replies open with a
      groan or a sigh, not all, and not always the same one.
- [ ] Ask for something long (a paragraph): his first sound comes well before
      the first sentence would have finished being made, and in
      `<data>/logs/speech.log` nothing waits. In the server log, "first sound
      made in" for a long first sentence is well under a second.
- [ ] A short reply then a long one ("Yeah. The duty point sits high because...")
      plays with no hole between the sentences.
- [ ] Watch his mouth as he talks: it opens on his words and closes on the
      pauses inside a sentence, and shuts as the sound ends, in Kit 3D and Kit
      2D. With his voice off it pulses as before.
- [ ] `curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"text":"Hi there."}' "http://<server>:8600/api/speech/say?wav=1" -o hi.wav`
      saves a playable WAV (the whole-clip option for older desks and tools).
- [ ] Send a new message while a long sentence is still being made: the server
      log shows the old line cut short and the new reply's sound comes within
      about half a second.

His voice on another computer (after [[Stage 3 - Voice#His voice on another computer|the steps above]]):

- [ ] `kit speech` on the server says the PC's voice is in use, and the link
      line shows the PC's name, `ready`, `cuda` and the CUDA graph on.
- [ ] `kit speech say "Testing from the PC"` on the server: the first sound
      comes in about the time it did when Kit ran on the PC (about 0.8 s for a
      short line), and the line shows how much of it was the PC making it.
- [ ] Chat in the desk app: his voice is Heart's, and the first sound comes as
      quickly as before.
- [ ] `sudo systemctl stop kit-voice` on the PC while he talks: he carries on in
      the server's voice from the next sentence, and `kit speech` says why.
      `sudo systemctl start kit-voice`: within a few seconds he's back in the
      PC's voice.
- [ ] Restart the PC: the voice program reconnects by itself once WSL is up.
- [ ] `kit speech off` on the server: the PC's graphics card memory is freed
      (`nvidia-smi`); `kit speech on` loads it again.
- [ ] After each switch his ears still ignore his own voice.
- [ ] `systemctl is-enabled kit` in WSL on the PC says `disabled`.
- [ ] `kit speech off`: within a few seconds `nvidia-smi` shows the memory freed,
      and replies are silent.
- [ ] `kit speech use kokoro` while speech is on: the next reply is in Kokoro's
      voice and Chatterbox's memory is freed.
