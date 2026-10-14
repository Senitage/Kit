---
tags: [reference, topic/settings]
aliases: [All settings, settings.toml reference, Config reference]
summary: Every setting Kit has, section by section, with its default and what it does. Change them on the settings page, in the desk app, in home_app or with kit config set.
---

# Settings reference

Up: [[Home]] · Reference

Every setting below lives in `config/settings.toml` in Kit's data folder.
Change one on the settings page, in the desk app's Kit's settings, in
home_app, or with `kit config set SECTION.NAME VALUE`. Changes apply from the
next message and can be undone. How that works is in [[Settings and Data]].

> [!TIP] The source of truth
> These tables come from `src/kit/settings.py`, where each setting's default
> and description live. `kit config schema` prints the same as JSON, and
> `kit config show` prints what's in force now. A test checks every setting
> is listed here.

## What the file holds

`settings.toml` starts with `schema_version = 3` and then holds **only what
you changed**. A setting that isn't in the file is at its default, so when a
default moves in a Kit update (a voice engine's field in `speech.engines`, a
line of his character in `persona`), it reaches you by itself. A built-in
voice engine is written the same way, field by field; an engine you added
yourself is written whole. The one exception is `models`: it's your own list,
so once it differs from the three starters it's written whole, and it never
holds a price.

- `kit config show` prints everything in force, defaults included; the file
  is the short version. Set a value equal to its default and it leaves the
  file.
- A value you type into the file by hand is yours, even if it equals today's
  default, until the next save from a page or `kit config set` tidies it out.
- **Version 2 files** (October 2026) took five built-in model profiles for
  granted, held prices as settings and the budget in US dollars. The first
  read keeps the models a role uses and any the file names (whole, without
  the prices), turns the budget into Australian dollars and rewrites the file
  as version 3. **Version 1 files** (before that) held every value, chosen or
  not; the defaults of the day are dropped first. Neither makes a history
  entry, and what you had changed stays. See
  [[Updating Kit#Settings from an older Kit]].

## ollama

The local model, run by Ollama on the server. See [[Models and Routing]].

| Setting | Default | What it does |
|---|---|---|
| `url` | `http://127.0.0.1:11434` | Address of the Ollama server on this machine. |
| `model` | `qwen3:8b` | Local model for everyday chat. |
| `num_ctx` | `8192` | Context window in tokens. Must hold the persona, memories and history; bigger uses more GPU memory. |
| `think` | off | Let the local model think before answering. Slower; off for chat. |
| `temperature` | `0.7` | Higher is livelier, lower is steadier. |
| `speak_pass` | on | Kit decides what to do in a quick JSON pass, then says his words in a second, plain-text pass at a livelier temperature. He sounds more like himself and repeats himself less; his first words come about half a second later. Off: one JSON pass, as in stage 1. |
| `keep_alive` | `30m` | How long the local chat model stays loaded on the GPU after it was last used (Ollama's keep_alive, e.g. 30m, 5m, 0). With routing.background on chat in cloud-only mode it is 2m whatever this says, so the voice has the card. |
| `speak_temperature` | `0.95` | Temperature for Kit's spoken words (with speak_pass) and his private thoughts. Higher is livelier and less predictable. |
| `min_p` | `0.05` | For his spoken words and thoughts: words less likely than this share of the likeliest one are never picked, which keeps a high temperature sensible. 0 is off. |
| `repeat_penalty` | `1.08` | For his spoken words: discourages reusing the same words. 1 is off. |
| `repeat_last_n` | `64` | For his spoken words: how many recent tokens repeat_penalty looks back over. 0 is off, -1 the whole context. |
| `top_k` | `64` | For his spoken words and thoughts: only the likeliest this many words are ever picked. 64 is what Gemma's makers suggest. 0 is off. |
| `top_p` | `0.95` | For his spoken words and thoughts: words are picked from the likeliest ones that make up this share of the chance. 1 is off. |
| `warm_up` | off | Read the conversation into the local model ahead of your next message, once Kit (and his voice) has finished, so he starts answering sooner. Some models (Gemma) re-read the whole prompt whenever anything in it changes, which took about two seconds a message. With this on, what changes every message (the time, what he recalled, your PC) goes beside your message instead of in his instructions. Not in cloud-only routing, where the local model only stands in. |

## routing

Which model answers what, and when Kit asks before spending. See [[Models and Routing]].

| Setting | Default | What it does |
|---|---|---|
| `mode` | `balanced` | How much Kit leans on the local model. local-heavy: the local model answers and only hands over what it can't do. balanced: the local model takes small talk and quick commands, the cloud takes real questions and work. cloud-first: the cloud answers everything. cloud-only: the chat model answers everything, even goodbyes and messages while another model is busy, and hands real work to the work model; the local model only steps in if the cloud fails (fallback_to_local) or you say 'keep it local'. |
| `chat` | `haiku` | Model profile that answers everyday messages in cloud-only mode, handing real work to the work model. |
| `work` | `sonnet` | Model profile for real questions, work and web searches. |
| `expert` | `opus` | Model profile for the hardest questions. |
| `confirm_expert` | on | When the work model decides a question needs the expert model, Kit asks you first and only hands it over if you say yes. Saying 'think hard' or 'ask the expert' still goes straight there. |
| `fallback_to_local` | on | If the cloud can't be reached (offline, no key, budget used up), the local model answers instead. |
| `background` | `local` | Who does Kit's own background work: his private thoughts (with you and on his own), his pipe-ups, and comparing something new you tell him with what he already knows. local: the local model. chat: the cloud (thoughts and pipe-ups by the chat model, about A$2 a month; fact comparisons by the work model, a cent or so), with the local model stepping in if the cloud can't. Anything from what you kept local stays on the local model either way. In cloud-only mode, chat also unloads the local model two minutes after it was last used, so the voice has the GPU. |
| `check_facts` | on | When you put something to Kit to agree with ("Sydney's the capital, isn't it?"), the work model checks it in a second or so, while Kit gets ready to answer, and he says the answer himself. Off: the local model goes by what it knows. |
| `key_moments` | on | For the moments that matter, the work model writes Kit's words, in his voice and mood: his hello after a night or more away, and his answer when you share something sad or stressful. A second or two slower; the local model steps in if the cloud can't. Never for 'keep it local'. |
| `key_moment_strength` | `0.7` | How strongly sad or stressful something you say has to land (0 to 1) to count as a key moment. 'Rough day' is about 0.8, 'bad news' 0.7. |
| `key_moment_hellos` | `overnight`, `days`, `long` | Which hellos count as key moments: after a while, hours, overnight, days or a week and more away. |

## models

The models Kit can use, by name: your own list. A new Kit starts with these
three; `kit models add NAME --provider P --model ID` adds any model,
`kit models remove NAME` takes one out (over the API, send it as `null`), and
`kit models ROLE NAME` gives a role one. What each costs isn't a setting:
`kit models` shows today's prices. See [[Models and Routing#Your own list of models]].

| Profile | Provider | Model |
|---|---|---|
| `haiku` | anthropic | Claude Haiku, no thinking first |
| `sonnet` | anthropic | Claude Sonnet |
| `opus` | anthropic | Claude Opus, room for a long think |

Each profile has these fields:

| Field | What it does |
|---|---|
| `label` | Name Kit uses when it mentions this model. |
| `provider` | Who runs it. anthropic, openai and google need an API key in Kit's secrets folder; ollama runs on this machine. |
| `model` | The provider's model id. |
| `effort` | How hard the model thinks before answering. Higher costs more. |
| `max_tokens` | Longest answer, thinking included, in tokens. 16000 unless set; the built-in `opus` profile has 32000, since an expert answer thinks at length first. |
| `thinking` | Let the model think before it answers. Off, the first words come sooner; only Claude Haiku takes it (Sonnet and Opus always think). The built-in `haiku` profile has it off. |
| `web_search` | Let the model search the web (the provider's own search). |

## cloud

The monthly budget for cloud models, in Australian dollars. See [[Models and Routing#The budget]].

| Setting | Default | What it does |
|---|---|---|
| `monthly_cap_aud` | `60.0` | Kit stops using cloud models once this month's spend reaches this, in Australian dollars. Every call is costed at the day's prices and exchange rate. |
| `reserve_aud` | `5.0` | As the budget runs low, cloud calls give way in order, each this much sooner than the last (in Australian dollars): evals first, then fact checks and key moments, then chat. Kit's nightly reflection always has the last of it. 0 treats them all the same. |
| `stream` | on | A Claude answer comes in as it's written, so Kit starts saying the first words (in the answer's mood) while the rest is still on its way. Goodbyes are still checked whole first. Off: each answer arrives in one piece. |

## nas

The NAS: the notes vault (the one place Kit may write) and shares he may only read. See [[Notes on the NAS]].

| Setting | Default | What it does |
|---|---|---|
| `read_only_shares` | none | Shares Kit may read but never change, by name. A UNC path on Windows (\\NAS\photo) or a mount point on Linux (/mnt/nas/photo). |
| `vault` | empty | The Obsidian vault folder, the only place on the NAS Kit may write. |
| `notes_folder` | empty | Where in the vault Kit saves notes Dan asks for, e.g. 'Inbox'. Empty for the vault's top level. |

## files

The folders Kit reads into his memory, and how. See [[Your Files]].

| Setting | Default | What it does |
|---|---|---|
| `roots` | none | The folders Kit indexes, by a short name you choose, each with `path` (the folder on the server; he only reads it), `private` (its contents stay with the local model), `ocr` (read scanned PDFs too; slow, needs the ocr extras) and `max_mb` (files bigger than this are skipped, default 50). Add them on the settings page ("Your files") or with `kit files add`. |
| `skip` | `.obsidian`, `.git`, `node_modules`, `@eaDir`, `#recycle`, `#snapshot`, `*.tmp`, `~$*` | Folder or file names (with `*` wildcards) never indexed, anywhere under a root. |
| `chunk_words` | `400` | About how many words each indexed piece of a file holds. |
| `max_rows` | `2000` | Most rows read from each sheet of a spreadsheet. |
| `sync_every_minutes` | `30` | How often Kit looks for new and changed files. 0 means once a day. |
| `read_words` | `1500` | Most words of one file Kit reads into an answer at once (used by the file tools). |

## persona

Who Kit is and who he's with. See [[Who Kit Is]].

| Setting | Default | What it does |
|---|---|---|
| `name` | `Kit` | The assistant's name. |
| `owner` | `Dan` | Who Kit works for. |
| `backstory` | built in | Who Kit is, in a sentence or two. |
| `traits` | built in | Three to five core traits. |
| `speech` | built in | How Kit talks: his register, decided here and nowhere else. The default: "Plain, neutral English, warm and friendly: short sentences and everyday words, with no slang or regional expressions. One or two sentences unless asked for detail. Matter-of-fact rather than gushing, and never 'as an AI'." The two older defaults are read as this one. A style copied from a character is only how he sounds: he still calls himself by `name`. |
| `location` | empty | Where the owner is, for weather and local searches, as 'city, state', e.g. Richmond, NSW. |
| `country` | empty | The owner's country as a two-letter code, e.g. AU. |
| `timezone` | empty | The owner's time zone, e.g. Australia/Sydney. |
| `knows` | "Only what they've told you so far; you're still getting to know them." | What Kit knows about the owner: who's at home, what they do for work, what they're into. A few lines in your own words; the built-in line says he's still getting to know you. Your real details belong here in your own `settings.toml`, never in the code: the repo is public. |
| `rules` | built in | Rules Kit always follows. {owner} stands for the owner's name. |
| `examples` | built in | Sample exchanges. Small models keep character best with a few of these. |

## brain

The brain's address and how conversations start and end. See [[Brain]].

| Setting | Default | What it does |
|---|---|---|
| `host` | `127.0.0.1` | Address the brain listens on. 127.0.0.1 is this PC only; 0.0.0.0 lets the home network and Tailscale in. |
| `port` | `8600` | Port for the chat page and API. |
| `new_chat_after_minutes` | `120` | Coming back after this long quiet, Kit picks up one thing from last time, as a new chat does; the conversation itself carries on, marked "(3 hours later)". 0 never does. |
| `new_topic_below` | `0.45` | A message this far in meaning from your last few (similarity below this, 0 to 1) is noted as a change of subject beside it; the conversation is kept. 0 never does. Short or 'that/it' messages never count as a new topic. |
| `history_messages` | `20` | Recent messages Kit sees each turn. |

## tools

The tool loop: how many times a turn the model may ask for a tool, which
packs a message loads, and what asks you first. See [[Tools and Packs]].

| Setting | Default | What it does |
|---|---|---|
| `hops` | `6` | Most tool calls in one turn (1 to 20). After this many the model is answered with what it has. |
| `packs` | `["all"]` | Which packs may load at all, by name (`kit tools packs`), or `all`. A pack left out is never offered. |
| `max_packs` | `3` | At most how many packs one message loads by meaning, the core pack included (1 to 10). Packs named by a word in the message, or by a register thing, load even past this. |
| `match_similarity` | `0.45` | How close in meaning a message must be to a pack's example questions to load that pack (0 to 1). Higher loads fewer. |
| `confirm` | `[]` | Tools, by name, that ask you first even though they only do something easily undone. Anything that changes something of yours always asks. |
| `confirm_lapse_minutes` | `10` | How long Kit waits for your yes to something he asked to do before letting it go (1 to 1440). |

## memory

How memories are found and kept. See [[Memory]].

| Setting | Default | What it does |
|---|---|---|
| `embed_model` | `nomic-embed-text` | Ollama model that turns text into meaning vectors, so Kit can find memories by meaning as well as by words. Changing it re-indexes everything. |
| `embed_keep_alive` | `24h` | How long the embedding model stays loaded after it was last used (Ollama's keep_alive, e.g. 24h, 30m, -1 for always). It is small, and recall needs it before every reply, so loading it again after a quiet spell would hold up the first answer. |
| `query_prefix` | `search_query: ` | Text the embedding model wants before a search. |
| `document_prefix` | `search_document: ` | Text the embedding model wants before stored text. |
| `relevant_memories` | `8` | Memories recalled into each turn, most relevant first. |
| `relevant_things` | `5` | Entries from the register of things recalled into each turn, with where each lives. Things named in the message always come first. |
| `conversation_snippets` | `4` | Older conversation snippets recalled into each turn. |
| `own_memories` | `3` | Entries from Kit's own notebook (his thoughts, opinions, moments and journal) recalled into each turn, most relevant first. |
| `min_similarity` | `0.59` | How close in meaning a memory must be to count as relevant (0 to 1). It depends on the embedding model: `kit eval memory` suggests a value. |
| `weight_floor` | `0.3` | Among relevant memories, the ones that matter more to your life and the ones you told Kit or confirmed lately come first; this is the least an old, small one counts (0 to 1). 1 weighs them all the same. |
| `now_days` | `14` | Days a 'now' memory lasts: how you've been or what's going on lately (flat out, crook, a visitor staying). Then it's forgotten; the day summaries keep the gist. |
| `day_pass` | `work` | Who reads each finished day after midnight, writes its summary and sorts what's worth remembering about you into the right kinds. work: the work model (Sonnet), a few cents a night, with the local model stepping in if the cloud can't; a day with something you kept local always stays home. local: the local model only. |
| `backups_keep` | `14` | Daily memory backups to keep. |

## life

His inner life and the companion habits. See [[Inner Life]] and [[Companion]].

| Setting | Default | What it does |
|---|---|---|
| `enabled` | on | Kit fidgets, gets bored and sometimes pipes up on his own. |
| `cheek` | `0.6` | How cheeky Kit is, in chat and when he pipes up: 0 polite, 1 very cheeky. |
| `chattiness` | `0.5` | How readily Kit speaks first. 0 never (he still fidgets), 1 whenever he feels like it, within the hourly limit. From 0.8 he follows along with what you're doing, nags when ignored and now and then butts in while you type. |
| `max_per_hour` | `3` | Most times an hour Kit pipes up unprompted. |
| `quiet_from` | `22:00` | Kit doesn't pipe up from this time... |
| `quiet_until` | `07:00` | ...until this time. |
| `sleep_after_minutes` | `10` | Kit dozes off after you've been away this long. Dozing while you're out lasts about two naps, then he gets up for this long before dozing again. |
| `naps` | on | Kit sometimes nods off for a nap when he's bored, nobody's talked to him for half an hour and nothing's going on, even with you at the PC. Never mid-conversation or in quiet hours, at most twice a day. Talking to him wakes him. |
| `nap_minutes` | `20` | Roughly how long a nap lasts (give or take a third). |
| `turns_in` | on | Past bedtime, once nobody's talked to him for a quarter of an hour, Kit goes to bed himself, even if you're still up. He gets up around the end of quiet hours. |
| `think_every_minutes` | `8` | Roughly how often Kit has a private thought in a quiet moment while you're around. Things happening (you coming back, something new on screen, a build failing, a chat ending) prompt one sooner. |
| `thoughts_per_hour` | `6` | Most thoughts Kit has in an hour (each is a quick local model call). 0 stops him thinking between conversations. |
| `reflect_with` | `cloud` | Who writes Kit's journal and self-sheet each night. cloud: the work model, a few cents a day, logged as spend (the local model steps in if the cloud can't). local: the local model only. off: Kit doesn't reflect or change. |
| `reflect_role` | `expert` | Which cloud model writes Kit's journal, self-sheet and what's going on with you each night (with reflect_with cloud). expert: Opus by default, about 2 to 4 cents a night. work: Sonnet, about half that. |
| `weekly_review` | on | Once a week the expert model reads how Kit has changed and writes a short review on the memory page, where you can undo any change (a few cents). |
| `homecoming` | on | Kit knows how long you've been away. Back after 20 minutes or more, he's glad and says hello once, asking how it went if you said where you were off to. Off: he just carries on. |
| `miffed` | on | After his first week, if you vanish for hours in the daytime without a goodbye, Kit is a bit miffed when you're back: one theatrical huff, then it's over. |
| `miffed_after_days` | `7` | Days from Kit's first start before he can be miffed, so his personality settles first. |
| `games` | on | At most once a day, when he's bored and you're around, Kit suggests a small game (a weather bet, a would-you-rather). Ones that keep falling flat retire. |
| `threads` | on | Kit follows what's coming up in your life when you mention it with a day or time ('dentist Thursday arvo') and asks how it went once it's over, once. Never for work. 'Ask me tomorrow...' and 'check in after my 2 pm' work either way. |
| `chat_opener` | on | When you come back to a new chat, Kit picks up one thing from the last one (how something went), the way a friend would. |
| `interview` | on | Kit gets to know you by chat: at most one everyday question a day (your partner's name, the cat's, your mates, what you like doing), until he knows. He skips what he already knows. |
| `nudges` | on | Once a day each: a nudge toward bed when you're still up past bedtime, and toward getting outside or seeing someone after a long stretch at the desk. |
| `bedtime` | `22:30` | When Kit starts nudging you toward bed (with nudges on), and from when he may turn in himself (with turns_in on). |
| `desk_hours` | `3.0` | Hours at the desk without a break before Kit nudges you outside (with nudges on, in the daytime). |
| `work_triggers` | off | Kit gets curious about work apps and sites (code, Teams, Excel, GitHub) and reacts to builds and tests on screen. Off: only everyday things catch his eye. |
| `alone_thoughts_per_hour` | `0` | While you're away and he's awake, Kit entertains himself (watching the weather, rereading yesterday's journal, thinking about someone in the register, listening to what's playing if the desk app shares it) and has this many private thoughts an hour about it, always with the local model, never in quiet hours. The desk face shows what he's doing. 0: he just waits, then dozes. |
| `week_thoughts` | off | Kit notices the shape of the week: a thought on Monday, Friday and Saturday mornings, and on WA public holidays. |
| `read_mood` | `words` | How Kit reads how you are. words: from what you say ("stressed", "legend"), ignoring "not stressed". meaning: the model answering also reads your mood, what it's about and whether things went as hoped, with the words as a floor. meaning needs a passed `kit eval mood` first; until then he uses words. |
| `mixed_feelings` | off | Kit can feel two things at once (chuffed at your praise and still a bit worried about your day). Off: the stronger feeling wins. |
| `bad_night` | on | When you sound like you're having a really bad time, Kit drops the cheek for the rest of the chat, listens and stays, and once mentions someone you can talk to or Lifeline (13 11 14). |
| `energy_need` | off | Energy is a real need: long chats, cloud jobs and staying up past 22:30 tire Kit out, and sleep restores him. His body clock winds him down from 21:00, so he's sleepy by 23:00 however rested. Below 0.4 he yawns and keeps replies short. Off: his energy just follows the clock. |
| `opinions` | `0` | How many of his standing opinions (from his notebook) Kit keeps in mind when he talks, so he sticks to them. |
| `dials` | off | Kit's mood also runs as two slow dials (how lively, how happy) that bodies show: slower breathing and blinks when he's flat or tired, bigger gestures when he's up. |
| `pipe_up_bar` | `0.0` | Before Kit brings something up unprompted, he scores it for relevance, originality and urgency (helped by how often you take his pipe-ups up) and keeps quiet below this. 0 turns the scoring off; 0.5 is a sensible bar. |
| `eyes_manners` | on | With his eyes on, Kit doesn't pipe up while you're on your phone or talking to someone, and his bubble says why. |
| `hold_pipe_ups` | off | Something Kit wanted to say while you were on your phone or talking to someone waits until you're done (up to half an hour), and he says why he waited. |
| `seen_feelings` | off | Kit feels what his eyes catch: a wave (he waves back), a thumbs up, a smile at him for a couple of seconds (he brightens), a frown that stays (he's sympathetic), and your eyes closing late at night (he yawns and thinks of bed). See [[Eyes#Moments he feels]]. |

## eyes

The camera, read by `kit eyes` on the PC. See [[Eyes]].

| Setting | Default | What it does |
|---|---|---|
| `enabled` | on | Kit uses a camera to see who's at the desk, when `kit eyes` is running on the PC with the webcam. |
| `camera` | `0` | Which camera the eyes use (`kit eyes cameras` lists them). |
| `width` | `1280` | Frame width to ask the camera for. |
| `height` | `720` | Frame height to ask the camera for. |
| `mirror` | on | Flip the picture like a mirror. On for a webcam facing you at the desk, so left is your left; off for a camera on the arm. |
| `detector` | `yolo11s` | The model that finds people and objects: yolo11s suits a PC with a graphics card, yolo11n is faster but mistakes mugs for phones, yolo11m is sharper still. Downloaded the first time the eyes run. |
| `detector_format` | `pytorch` | How the detector runs. pytorch suits a graphics card; openvino is quickest on an Intel CPU, ncnn on a Raspberry Pi, onnx anywhere. Anything but pytorch is made from the downloaded model the first time, at detector_size. |
| `detector_size` | `640` | The picture size the detector works at. 320 is about three times quicker on a CPU and still finds people and pets at desk distance; small things across the room get missed. |
| `device` | `auto` | Where the detector runs: auto uses the graphics card if there is one, cpu leaves the graphics card free for other things. |
| `confidence` | `0.4` | How sure the detector must be before something counts. |
| `looks_per_second` | `0` | How many frames a second the eyes look at. 0 looks at every frame the camera gives; 5 is plenty to follow a face on a CPU. |
| `detect_every` | `1` | Run the detector on one look in this many. Faces and hands are still read on every look, so his eyes keep following you while the detector rests. |
| `forget_after_s` | `3.0` | Seconds out of view before someone or something has left. |
| `report_every_s` | `1.0` | How often the eyes tell the brain what they see. |
| `faces` | on | Read faces: where each person is looking and their expression. |
| `hands` | on | Read hand gestures: thumbs up, open palm, a wave. |
| `poses` | `1` | How many people to read body pose for (each adds about 13 ms a frame). 0 turns it off. |
| `recognise` | on | Tell people apart by their faces, once they've been introduced with `kit eyes enrol NAME`. Kit keeps numbers worked out from a face, never pictures. |
| `match` | `0.4` | How alike a face must be to someone Kit knows to count as them. Higher is stricter: fewer mix-ups, but more 'someone I don't know'. |

## hearing

The microphone, read by `kit hearing` on the PC. Sound never leaves that PC.
See [[Hearing]].

| Setting | Default | What it does |
|---|---|---|
| `enabled` | on | Kit listens through a microphone when `kit hearing` is running on the PC with the mic. The tray's "Let Kit hear me" switch turns it off and on. |
| `mic` | empty | Which microphone to use: part of its name, or its number from `kit hearing mics`. Empty uses the PC's default. |
| `names` | `["Kit", "Kitt", "Ki", "Kid"]` | What Kit answers to. Said at the start or end of a sentence ("Kit, what's the weather?"), it means you're talking to him. After his name come the ways the ears sometimes write it; `kit hearing --words` shows what they hear, so add a word they often hear instead. |
| `follow_up_s` | `8.0` | After Kit stops talking, this many seconds when you can answer him without saying his name. 0 means always say his name. |
| `barge_in` | on | Talking over Kit stops him, as typing does. His own voice from the speakers doesn't count. |
| `barge_in_ms` | `500` | How long you must talk over Kit before he stops (milliseconds). |
| `laugh_s` | `10.0` | A laugh within this many seconds of Kit saying something makes him chuffed. 0 turns it off. |
| `tone` | on | Kit notices how you sound (down, cross, cheerful). He may ask about it, never tells you how you feel. |
| `match` | `0.45` | How alike a voice must be to someone Kit knows to count as them (`kit hearing enrol NAME`). Higher is stricter. |
| `own_voice` | `0.5` | How alike a voice must be to Kit's own for him to know it's himself coming back from the speakers, while he's talking. It must also be more like him than like anyone he knows. Lower ignores more. |
| `threshold` | `0.5` | How sure the voice detector must be that a sound is speech. Higher ignores more background noise, but may miss quiet speech. |
| `pause_ms` | `600` | How long a pause ends what you're saying (milliseconds). Shorter answers sooner; too short cuts you off mid-thought. |
| `min_speech_s` | `0.4` | Shorter sounds than this are ignored (a cough, a click). |
| `max_speech_s` | `20.0` | Longest stretch of talking heard as one go. |
| `language` | `en` | The language Kit's ears listen for: `en`, `zh`, `ja`, `ko`, `yue`, or `auto`, which works it out each time, a little less reliably. |
| `threads` | `2` | Processor threads the speech models use on the mic's PC. Up to about half its cores makes the words come sooner. |

## speech

His voice. See [[Voice]].

| Setting | Default | What it does |
|---|---|---|
| `enabled` | off | Kit speaks his replies aloud in the desk app. |
| `engine` | `kokoro` | Which voice engine profile Kit speaks with (see engines). |
| `engines` | built in | Voice engines Kit can use, by name. Built-in profiles are always there; change their fields or add your own (e.g. a second kokoro voice). |
| `port` | `8611` | Local port for the voice engine's program. |
| `load_timeout_s` | `240` | How long a voice engine may take to load (the first Chatterbox start downloads its model). |
| `sounds` | off | Sounds in his voice where a gesture calls for one: a chuckle on the punchline, a sigh, a gasp. At most one every other sentence. Only Chatterbox Turbo makes them; other engines leave them out. |
| `fallback` | (none) | A voice engine to switch to if his usual one can't start or runs out of graphics card memory (e.g. kokoro, on the CPU). He stays on it until his speech settings change. Empty: no fallback, his voice just stops. |

### Voice engine profiles

`speech.engines` holds the voice engines by name: `chatterbox-turbo`,
`chatterbox`, `kokoro`, `piper` and `tone` are built in. Each has these fields:

| Field | What it does |
|---|---|
| `kind` | Which engine: kokoro and piper are fast on a CPU; chatterbox is the most expressive (GPU); chatterbox-turbo is faster but has no emotion dial; tone beeps, for testing. |
| `python` | The Python that has this engine installed. Empty: the Python running Kit. |
| `device` | Chatterbox only: auto uses the graphics card if there is one. |
| `voice` | kokoro: a voice name such as af_heart. piper: the voice's .onnx file. |
| `reference` | chatterbox: a clip of at least 6 seconds whose voice Kit copies. Empty: Chatterbox's own voice. |
| `speed` | kokoro and piper: talking speed. |
| `mood_speed` | kokoro and piper: speed change per emotion. |
| `exaggeration` | chatterbox: how strongly each emotion is acted out, 0 to 2. |
| `cfg_weight` | chatterbox: lower is slower and more deliberate. |
| `mood_tags` | chatterbox-turbo: sounds that may open a reply in that emotion, such as `[sigh]` or `[chuckle]`; one is picked at random each time (a single sound works too). See [[Voice#Sounds in his voice]]. |
| `mood_tag_chance` | chatterbox-turbo: how often a reply in one of those emotions opens with a sound (0.6: six in ten); the rest just start. |
| `cuda_graph` | chatterbox-turbo on a graphics card: record its token loop as a CUDA graph, about 2.4 times faster with the same voice. Off: Chatterbox's own loop. On by default. See [[Voice#Faster on a graphics card]]. |

## face

How he looks. See [[Face]].

| Setting | Default | What it does |
|---|---|---|
| `character` | `retro` | Which character Kit is: how he looks and moves in the desk app, home_app and on his robots. Retro is the original glowing pill eyes; switch back any time. |
| `hot_c` | `35.0` | When you ask about the weather, a dry day this hot or hotter (°C) shows as a hot day on his face: the sun beating down and him sweating. |
| `pack_folder` | empty | A folder holding a 3D face pack (face.json and the .glb) to use for a 3D character instead of the one built into Kit, e.g. the pack folder your Blender project writes. Each rebuild shows on the desk within seconds. Empty: built in. |
