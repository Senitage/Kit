---
tags: [reference, topic/glossary]
aliases: [Words, Terms, Jargon]
summary: The words these docs use for Kit's parts, in alphabetical order, each with a line of meaning and the note that explains it.
---

# Glossary

Up: [[Home]] · Reference

| Word | Means | See |
|---|---|---|
| **Action** | Something Kit does mid-answer: remember, recall, take a note, look at the PC, look around | [[Brain#What he can do mid-answer]] |
| **Body** | Anywhere Kit appears and acts out the brain's events: the desk app, home_app, the Pod, the arm | [[Bodies]] |
| **Body feed** | The plain-text lines a small board like the Pod's reads, one per thing (`emotion happy`) | [[Pod In Depth#The body feed]] |
| **Body move** | A whole-body move by name: a hop, a loop, a sway | [[Face#Body moves]] |
| **Aside** | A stage direction in square brackets beside your message (a hello, a bedtime nudge, a bad night); at most two ride with one message | [[Brain#One voice, two asides at most]] |
| **Backup voice** | The voice engine he switches to if his usual one fails (`speech.fallback`) | [[Voice#A backup voice]] |
| **Brain** | The server program that thinks, remembers and decides; everything else is a body or a sense | [[Brain]] |
| **Calm neck** | The Pod's rule that his face is lively but his head only moves when he pays attention to something | [[Pod In Depth#The calm neck]] |
| **Channel** | Where you're talking from: desk, voice, phone, web, home, terminal | [[Brain#Where you're talking from]] |
| **Character sheet** | One file saying how Kit looks and moves: Retro, Kit 3D, Kit 2D | [[Face]] |
| **Check-in** | The one gentle pipe-up he allows himself on a bad night, asking if you're okay | [[Inner Life In Depth#A bad night]] |
| **Cheek** | How cheeky he is, 0 to 1 (`life.cheek`) | [[Inner Life]] |
| **CUDA graph** | GPU work recorded once and replayed in one go; it makes Chatterbox Turbo's voice about 2.4 times faster | [[Voice#Faster on a graphics card]] |
| **Data folder** | The one folder holding everything Kit owns | [[Settings and Data]] |
| **Day summary** | What Kit writes after midnight about each finished day | [[Memory]] |
| **Device token** | A token just for one paired device, like a phone, so it can be unpaired alone (`kit pair`) | [[Phone App#Pairing]] |
| **Drives** | What rises and falls in him: boredom, curiosity, wanting a chat, something to say, energy | [[Inner Life#Drives and mood]] |
| **Embedding** | A meaning vector: numbers that let him find things by what they mean | [[Memory#Finding things]] |
| **Emotion** | One of 17 feelings a reply is acted out in | [[Face#Emotions and gestures]] |
| **Eval** | A repeatable check of how the real models behave | [[Evals]] |
| **Echo** | Kit's own voice from the speakers coming back through the mic; his ears know it and ignore it | [[Hearing#His own voice]] |
| **Ears** | The microphone program that tells the brain what it heard, in words, never sound | [[Hearing]] |
| **Eyes** | The camera program that tells the brain what it sees, in words | [[Eyes]] |
| **Follow-up window** | The few seconds after Kit stops talking when you can answer without his name | [[Hearing#When he answers]] |
| **Fact** | One thing Kit knows about you, with its kind and history | [[Memory]] |
| **Features** | What the brain can do, each with a version number, sent to a body when it says hello | [[Phone App#Saying hello]] |
| **Generation (voice)** | The number a reply's sentences carry to the voice engine; a sentence from a lower number than one already seen is dropped, so interrupting him doesn't leave the engine finishing the old reply | [[Voice#How a sentence becomes sound]] |
| **Held pipe-up** | Something he wanted to say while you were busy, saved till you're free | [[Inner Life In Depth#Busy and held pipe-ups]] |
| **Gesture** | One of 20 short face clips: a nod, a wink, a shrug | [[Face#Emotions and gestures]] |
| **Glow** | The original 2D painter: two glowing pill eyes | [[Face]] |
| **Hello** | A body introducing itself to the brain with what it can do (`/api/bodies/hello`) | [[Phone App#Saying hello]] |
| **Key moment** | A moment that matters, where a stronger model writes his words | [[Models and Routing]] |
| **Keep it local** | Words that keep a message and all that comes of it away from cloud models | [[Privacy#Keep it local]] |
| **Kit 2D** | The 3D face drawn flat, for small screens like the Pod's | [[Face]] |
| **Kit 3D** | The Blender face, served by the brain as a live page | [[Face]] |
| **Notebook** | Kit's own book: thoughts, opinions, wants, threads, moments, journal | [[Inner Life#Thoughts and his notebook]] |
| **Pack** | The 3D face's model and tuning (`face.json` and a `.glb`) | [[Face In Depth]] |
| **Pairing** | Giving a device its own token: from the app with Kit's address and token, or a QR code from `kit pair` | [[Phone App#Pairing]] |
| **Piece** | A bit of a sentence's sound (about a second), sent to the desk while the rest is still being made | [[Voice#How a sentence becomes sound]] |
| **Pipe-up** | Kit saying something without being asked | [[Inner Life#Piping up, with manners]] |
| **Pod** | Kit's first robot: a small desk Pod with a screen face and a turning head | [[The Pod]] |
| **Reading** | What your message is, as read: the words guess (a goodbye, news, about Kit, a bad-night phrase), then the model's plan decides (`intent`, `about_kit`, `wants_pc_look`, `wants_camera_look`, `said_it`, `crisis_candidate`) | [[Brain#The reading: judgement over keywords]] |
| **Register of things** | The list of people, vehicles, places, projects and equipment, and where each lives | [[Register of Things]] |
| **Replay eval** | `kit eval memory --replay`: your own questions asked of a copy of a real memory backup, to see the right fact still comes first | [[Evals]] |
| **Retro** | The default character: Glow's pill eyes | [[Face]] |
| **Rig** | What turns emotions and gestures into face numbers | [[Face#The rig, in three layers]] |
| **Role** | A job a model does: chat, work, expert | [[Models and Routing]] |
| **Routing** | Deciding which model answers a message | [[Models and Routing]] |
| **Scene** | What the eyes see right now, in words and numbers | [[Eyes]] |
| **Schema version** | The settings file's layout; from version 2 the file holds only what you changed | [[Settings Reference#What the file holds]] |
| **Seen moment** | A small thing his eyes catch that he feels: a wave, a smile, a frown | [[Eyes#Moments he feels]] |
| **Self-sheet** | Who Kit thinks he is, in his own words, rewritten nightly | [[Inner Life#Each night he looks back]] |
| **Show** | Something his face shows instead of his eyes: the time, the date, the weather | [[Face#Shows for the time, date and weather]] |
| **Sound** | A chuckle, sigh or gasp in his voice, inside his words | [[Voice#Sounds in his voice]] |
| **Source** | A kind of thing in the memory index: facts, days, conversations, things, notes, his notebook | [[Memory#What's in it]] |
| **Talking over him** | Starting to talk while Kit speaks; he stops, as he does when you type (`hearing.barge_in`) | [[Hearing#Talking over him]] |
| **Thread** | Something coming up in your life that he'll ask about after | [[Companion#He follows your life]] |
| **Token** | The password every app uses to talk to the brain (`kit token`) | [[Privacy#Tokens and secrets]] |
| **Tone** | How a voice sounded (cheerful, down, cross), read from the sound; he may ask, never tells | [[Hearing#Tone and laughs]] |
| **Two passes** | Deciding what to do in one model call, then saying it in a second | [[Brain#Two passes when the local model talks]] |
| **Voice print** | 512 numbers worked out from a few seconds of someone talking; no sound can be rebuilt from them | [[Hearing#Whose voice]] |
| **Vault** | A folder of markdown notes Obsidian opens: your notes on the NAS, or these docs | [[Notes on the NAS]], [[How These Docs Work]] |
