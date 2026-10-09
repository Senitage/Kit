# Stage 3, part 1: Kit's voice

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
  desk app cuts the words into sentences as they stream in (a long first sentence
  is cut at its first comma), asks the server for each one, and plays it while the
  next is being made. So Kit starts talking about one sentence after the brain
  does, not after the whole reply.
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

1. Update Kit (`git pull`, then `pip install -e .`) and restart it
   (`sudo systemctl restart kit`). Install the desk app build from the same
   change: it brings the `sounddevice` package with it. Until the voice is merged,
   that's a test build, and the desk app won't offer to swap it for a release
   without the voice (see [the desk app guide](desk-app/README.md#updates)).
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
   (setuptools still carries `pkg_resources`, which Chatterbox's watermarker needs).
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
- [ ] `kit speech use chatterbox-turbo` and `kit speech on`, then in the desk app's
      chat, ask something. Kit starts speaking after his first sentence and the
      rest follows without gaps.
- [ ] The first word of each reply is whole: no missing first letters.
- [ ] A one-sentence reply starts speaking about a second after its words would
      have shown, and the words appear as he says them.
- [ ] Ask something, then send a new message while he's talking: he stops at
      once, and the rest of what he was saying shows above your message.
- [ ] When Kit pipes up by himself, he says it out loud.
- [ ] Untick "Show Kit's words as he says them" on the Look page: words appear as
      they stream in again, and he still speaks.
- [ ] With routing other than cloud-only, `kit config set ollama.warm_up true`,
      then chat for a few turns. In `<data>/logs/kit.log`, each message's first
      `local model: read N tokens` line drops from thousands of tokens to a few
      hundred from the second message on, and replies start sooner.
- [ ] Ask something that makes him grumpy or tired: Turbo opens with a groan or sigh.
- [ ] `kit speech off`: within a few seconds `nvidia-smi` shows the memory freed,
      and replies are silent.
- [ ] `kit speech use kokoro` while speech is on: the next reply is in Kokoro's
      voice and Chatterbox's memory is freed.
