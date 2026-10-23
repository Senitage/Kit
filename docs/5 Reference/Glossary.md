---
tags: [reference, topic/glossary]
aliases: [Words, Terms, Jargon]
summary: The words these docs use for Kit's parts, in alphabetical order, each with a line of meaning and the note that explains it.
---

# Glossary

Up: [[Home]] · Reference

| Word | Means | See |
|---|---|---|
| **Action** | Something a reply asks for once the words are out: remember, take a note, a thing for the register, hand off to a bigger model. The looks became tools | [[Brain#What he can do mid-answer]] |
| **Activity day** | One short memory item a day of what you did on the PC: apps and how long, files, sites, projects | [[Desk App#What you worked on]] |
| **Body** | Anywhere Kit appears and acts out the brain's events: the desk app, home_app, the Pod, the arm | [[Bodies]] |
| **Body feed** | The plain-text lines a small board like the Pod's reads, one per thing (`emotion happy`) | [[Pod In Depth#The body feed]] |
| **Body move** | A whole-body move by name: a hop, a loop, a sway | [[Face#Body moves]] |
| **Area** | A room as Home Assistant knows it; a thing's room is its own area or its device's | [[The House#Only what you expose]] |
| **Aside** | A stage direction in square brackets beside your message (a hello, a bedtime nudge, a bad night); at most two ride with one message | [[Brain#One voice, two asides at most]] |
| **Backup voice** | The voice engine he switches to if his usual one fails (`speech.fallback`) | [[Voice#A backup voice]] |
| **Brief** | The morning brief: a few short things worth knowing (weather, tasks, a bill, the house, yesterday), once a morning at the desk or in his first answer | [[Companion#The morning brief]] |
| **Brain** | The server program that thinks, remembers and decides; everything else is a body or a sense | [[Brain]] |
| **Calm neck** | The Pod's rule that his face is lively but his head only moves when he pays attention to something | [[Pod In Depth#The calm neck]] |
| **Contents tool** | A tool an app's MCP server offers that lists its saved work as rows, which Kit reads into memory once a day | [[Other Apps#Apps as packs]] |
| **Capability pack** | A named set of tools with one card (the line in his prompt): `core` first, then files, the PC, the house, the notes vault, your apps | [[Tools and Packs#Packs]] |
| **Channel** | Where you're talking from: desk, voice, phone, web, home, terminal | [[Brain#Where you're talking from]] |
| **Character sheet** | One file saying how Kit looks and moves: Retro, Kit 3D, Kit 2D | [[Face]] |
| **Check-in** | The one gentle pipe-up he allows himself on a bad night, asking if you're okay | [[Inner Life In Depth#A bad night]] |
| **Cheek** | How cheeky he is, 0 to 1 (`life.cheek`) | [[Inner Life]] |
| **Chunk** | One indexed bit of a file, about 400 words cut at paragraphs, from one page, sheet or slide; `kit files status` counts them as pieces | [[Your Files#How it works]] |
| **CUDA graph** | GPU work recorded once and replayed in one go; it makes Chatterbox Turbo's voice about 2.4 times faster | [[Voice#Faster on a graphics card]] |
| **Data folder** | The one folder holding everything Kit owns | [[Settings and Data]] |
| **Day summary** | What Kit writes after midnight about each finished day | [[Memory]] |
| **Desk command** | Kit asking the desk app to open something or press a key; the PC claims it, does it within its own rules and says how it went | [[Desk App#Doing things on the PC]] |
| **Device token** | A token just for one paired device, like a phone, so it can be unpaired alone (`kit pair`) | [[Phone App#Pairing]] |
| **Drives** | What rises and falls in him: boredom, curiosity, wanting a chat, something to say, energy | [[Inner Life#Drives and mood]] |
| **Effect** | What a tool does to the world: `read` (looks something up), `act` (easily undone, like a lamp) or `change` (alters something of yours, so it asks first) | [[Tools and Packs#Packs]] |
| **Embedding** | A meaning vector: numbers that let him find things by what they mean | [[Memory#Finding things]] |
| **Emotion** | One of 17 feelings a reply is acted out in | [[Face#Emotions and gestures]] |
| **Eval** | A repeatable check of how the real models behave | [[Evals]] |
| **Echo** | Kit's own voice from the speakers coming back through the mic; his ears know it and ignore it | [[Hearing#His own voice]] |
| **Ears** | The microphone program that tells the brain what it heard, in words, never sound | [[Hearing]] |
| **Eyes** | The camera program that tells the brain what it sees, in words | [[Eyes]] |
| **Exposed** | A Home Assistant thing you've exposed to Assist; the only things in the house Kit can see or switch | [[The House#Only what you expose]] |
| **Follow-up window** | The few seconds after Kit stops talking when you can answer without his name | [[Hearing#When he answers]] |
| **Fact** | One thing Kit knows about you, with its kind and history | [[Memory]] |
| **Features** | What the brain can do, each with a version number, sent to a body when it says hello | [[Phone App#Saying hello]] |
| **Generation (voice)** | The number a reply's sentences carry to the voice engine; a sentence from a lower number than one already seen is dropped, so interrupting him doesn't leave the engine finishing the old reply | [[Voice#How a sentence becomes sound]] |
| **Held call** | A tool call that changes something of yours, waiting for your yes before it runs | [[Tools and Packs#Asking first]] |
| **Held pipe-up** | Something he wanted to say while you were busy, saved till you're free | [[Inner Life In Depth#Busy and held pipe-ups]] |
| **Gesture** | One of 20 short face clips: a nod, a wink, a shrug | [[Face#Emotions and gestures]] |
| **Glow** | The original 2D painter: two glowing pill eyes | [[Face]] |
| **Hello** | A body introducing itself to the brain with what it can do (`/api/bodies/hello`) | [[Phone App#Saying hello]] |
| **Key moment** | A moment that matters, where a stronger model writes his words | [[Models and Routing]] |
| **Keep it local** | Words that keep a message and all that comes of it away from cloud models | [[Privacy#Keep it local]] |
| **Kit 2D** | The 3D face drawn flat, for small screens like the Pod's | [[Face]] |
| **Kit 3D** | The Blender face, served by the brain as a live page | [[Face]] |
| **Lite eyes** | The eyes set up to run on a CPU: a small detector a few times a second, faces read in between | [[Eyes#Without a graphics card]] |
| **MCP** | Model Context Protocol: a shared way for an app to list its tools and run them. Kit is the client; each app's server becomes a pack | [[Other Apps#Apps as packs]] |
| **Match words** | A pack's words that load it when one is in your message as a whole word | [[Tools and Packs#Which packs load]] |
| **Notebook** | Kit's own book: thoughts, opinions, wants, threads, moments, journal | [[Inner Life#Thoughts and his notebook]] |
| **Hop** | One go round the tool loop: the model asks for a tool, the brain runs it, the result goes back (`tools.hops` a turn) | [[Tools and Packs]] |
| **Pack** | The 3D face's model and tuning (`face.json` and a `.glb`); for a set of tools, see capability pack | [[Face In Depth]] |
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
| **Root** | A folder you chose for Kit to read into his memory, by a short name (`files.roots`) | [[Your Files#Choosing folders]] |
| **Routing** | Deciding which model answers a message | [[Models and Routing]] |
| **Scene** | What the eyes see right now, in words and numbers | [[Eyes]] |
| **Price list** | What every model costs, fetched daily from LiteLLM's list with the day's exchange rate, shown in Australian dollars | [[Models and Routing#Prices, fetched for you]] |
| **Schema version** | The settings file's layout; from version 2 the file holds only what you changed, from version 3 the models are your own list and prices aren't in it | [[Settings Reference#What the file holds]] |
| **Seen moment** | A small thing his eyes catch that he feels: a wave, a smile, a frown | [[Eyes#Moments he feels]] |
| **Self-sheet** | Who Kit thinks he is, in his own words, rewritten nightly | [[Inner Life#Each night he looks back]] |
| **Show** | Something his face shows instead of his eyes: the time, the date, the weather | [[Face#Shows for the time, date and weather]] |
| **Sound** | A chuckle, sigh or gasp in his voice, inside his words | [[Voice#Sounds in his voice]] |
| **Source** | A kind of thing in the memory index: facts, days, conversations, things, notes, his notebook | [[Memory#What's in it]] |
| **Talking over him** | Starting to talk while Kit speaks; he stops, as he does when you type (`hearing.barge_in`) | [[Hearing#Talking over him]] |
| **Task** | A `- [ ]` line in your notes. Each open one is its own item in his memory (the `tasks` source), with its due date | [[Notes on the NAS#Finding notes and tasks]] |
| **Thread** | Something coming up in your life that he'll ask about after | [[Companion#He follows your life]] |
| **Token** | The password every app uses to talk to the brain (`kit token`) | [[Privacy#Tokens and secrets]] |
| **Tool** | Something a model can call mid-answer and get a result back from: search memory, look at the PC, the forecast, a note | [[Tools and Packs]] |
| **Tool loop** | The model asks, the brain runs the tool, the model answers from the result, a few times a turn if need be | [[Tools and Packs#How it works]] |
| **Tone** | How a voice sounded (cheerful, down, cross), read from the sound; he may ask, never tells | [[Hearing#Tone and laughs]] |
| **Two passes** | Deciding what to do in one model call, then saying it in a second | [[Brain#Two passes when the local model talks]] |
| **Undo file** | A note as it was before Kit changed it, kept in `state/notes/undo` so "undo that" can put it back | [[Notes on the NAS#Changing a note]] |
| **Voice link** | The WebSocket the voice program keeps open to Kit, which his sentences go out on and their sound comes back on | [[Voice#His voice from another computer]] |
| **Voice print** | 512 numbers worked out from a few seconds of someone talking; no sound can be rebuilt from them | [[Hearing#Whose voice]] |
| **Voice program** | `kit voice`: makes his voice on another computer's graphics card and dials in to Kit for the lines | [[Voice#His voice from another computer]] |
| **Vault** | A folder of markdown notes Obsidian opens: your notes on the NAS, or these docs | [[Notes on the NAS]], [[How These Docs Work]] |
