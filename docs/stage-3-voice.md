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
- **Mood.** Kit's emotion sets `exaggeration` for Chatterbox (per emotion, in
  `speech.engines.chatterbox.exaggeration`), an opening sound for Turbo
  (`mood_tags`), and a small speed change for Kokoro and Piper (`mood_speed`).
- **Dan talking stops Kit.** Sending a message drops whatever Kit hadn't said yet;
  the sentence playing at that moment finishes.
- **Speech off** (`kit speech off`) stops the engine within a few seconds, which
  frees its memory. With speech on, the server loads the engine at start-up, so
  the first reply isn't kept waiting.

## Set it up on the server

1. Update Kit (`git pull`, then `pip install -e .`) and restart it
   (`sudo systemctl restart kit`).
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
- [ ] Ask something, then send a new message while he's talking: he stops after
      the current sentence.
- [ ] Ask something that makes him grumpy or tired: Turbo opens with a groan or sigh.
- [ ] `kit speech off`: within a few seconds `nvidia-smi` shows the memory freed,
      and replies are silent.
- [ ] `kit speech use kokoro` while speech is on: the next reply is in Kokoro's
      voice and Chatterbox's memory is freed.
