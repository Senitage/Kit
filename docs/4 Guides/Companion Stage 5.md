---
tags: [guide, stage, topic/companion, topic/hearing]
aliases: [stage-companion-5, Hearing Stage, Stage 3 part 2]
summary: Companion stage 5 - Kit hears you - installing the ears beside the mic, introducing voices, and the test checklist (answered from the couch, a laugh, talking over him, the partner greeted as themselves).
related: ["[[Hearing]]", "[[Companion]]", "[[Voice]]"]
---

# Companion stage 5: he hears you

Up: [[Home]] · Guides · [[Companion]]

The last stage of the companion plan, and part 2 of stage 3 (voice and
hearing). Kit already talks; now he listens:

- **Say his name and he answers out loud,** from anywhere the mic can hear
  you. For a few seconds after he stops, you can answer without his name.
- **Talk over him and he stops,** the way he does when you type.
- **Laugh at his joke and he's chuffed.**
- **He hears how you sound,** and may ask, but never tells you how you feel.
- **He knows voices** you introduce, so your partner is answered as
  themselves.
- **Sound never leaves the PC with the mic.** Talk that isn't meant for him is
  let go.

How it works is in [[Hearing]].

## 1. Update and restart Kit

Update and restart the brain as in [[Updating Kit]]. There are no new packages
on the server, and no memory upgrade. **The desk app** gets a tray switch,
**Let Kit hear me**, and plays his answers to what he heard; both come with its
update.

## 2. Install the ears on the PC with the mic

Like the eyes, the ears are the `kit` package with an extra, on the PC with the
microphone. Use the eyes' copy of Kit if you have one; otherwise make one as
in [[Vision Stage 1]], then:

```powershell
cd C:\path\to\Kit
.eyes\Scripts\activate
git pull
pip install -e ".[hearing]"     # sherpa-onnx and sounddevice; no PyTorch
kit hearing mics                # which microphones this PC has
kit hearing connect http://kit-server:8600 TOKEN   # once, if the eyes aren't set up
```

If `pip` says the file `kit.exe` is in use, the eyes are running from this copy.
Stop them (`Get-Process kit | Where-Object Path -like "*\.eyes\*" | Stop-Process`,
which leaves the desk app alone), install again, then start them again.

If the default mic isn't the one you want, set `hearing.mic` to part of its
name: `kit config set hearing.mic "Headset"`.

## 3. Open them

```powershell
kit hearing
```

The first start downloads three models into `%APPDATA%\Kit Hearing\models`
(about 200 MB, once). Then it says "Kit's ears are open". Each thing it hears
shows as one line: how long, whose voice, and what Kit made of it. The words
only show if you start them with `kit hearing --words`, and only in that
window.

To start them with Windows, add a logon task the same way as the eyes'
([[Vision Stage 1#4. Open them]]), with `kit hearing` as the command.

## 4. Introduce voices

```powershell
kit hearing enrol me        # you; read the lines it shows, at your usual distance
kit hearing enrol Sam       # anyone else, with their say-so
kit hearing voices          # who his ears know
```

Stop `kit hearing` first if your mic can only be opened once. Running ears
pick new voices up by themselves.

## 5. Test before moving on

- [ ] **From the couch:** "Kit, what's the weather doing?" He answers out
  loud, and it shows in the desk chat as your line and his reply.
- [ ] **Answer him:** reply to him within a few seconds without his name. He
  carries on.
- [ ] **Overheard:** talk about him without his name ("I told Kit about it")
  or have the TV on. Nothing happens, and `kit hearing show` says "not talking
  to him".
- [ ] **Laugh:** laugh at something he says. `kit life` shows him chuffed,
  "because you laughed", and his face laughs.
- [ ] **Talk over him:** ask him something long and start talking halfway.
  He stops within about half a second, and answers what you said.
- [ ] **His own voice:** with speakers, not a headset, let him finish a long
  answer. He doesn't stop himself or answer himself.
- [ ] **Tone:** say "Kit, I'm home" sounding flat. He's gentle and may ask how
  you are; he doesn't say "you sound sad".
- [ ] **Your partner:** after `kit hearing enrol NAME` for them, they say "Kit,
  hello". He answers them by name.
- [ ] **Asleep:** while he's napping, talk near the mic: he sleeps on. Say his
  name: he wakes.
- [ ] **The switch:** untick **Let Kit hear me**. The ears say "paused: the
  mic is off", and "can you hear me?" gets an honest no.

## If something's off

- **He never answers:** `kit hearing show` says whether the ears are
  listening. If it's "not talking to him", the mic heard you but not his name.
  Run `kit hearing --words` to see the words they heard (only in that window),
  then say his name at the start or end, or add the word they write instead to
  `hearing.names` on the server (`kit config set hearing.names
  '["Kit", "Kitt", "Ki", "Kid", "Kip"]'`). A `hearing.names` already in your
  settings file replaces the default list, so check it has "Ki" and "Kid".
- **He stops himself mid-sentence:** his own voice is coming back loud enough
  to sound like someone else. Lower `hearing.own_voice` a little, turn the
  speakers down, use a headset, or set `hearing.barge_in` to false.
- **He ignores you talking over him ("his own voice"):** `kit hearing --words`
  shows how alike each stretch was to his voice and to yours. If yours sounds
  more like him than like you, introduce yourself again (`kit hearing enrol
  me`) at your usual distance, or raise `hearing.own_voice`.
- **He cuts you off mid-thought:** raise `hearing.pause_ms`.
- **The fridge or fan sets it off:** raise `hearing.threshold`.
- **He calls you by your partner's name:** introduce both of you again in the
  same spot, or raise `hearing.match`.
- **"no microphone called ..."**: `kit hearing mics` lists the names; set
  `hearing.mic` to part of one, or leave it empty for the default.
