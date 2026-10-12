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

The models Kit can use, by name. The built-in profiles are always there; change
their fields or add your own, then give a role one with
`kit models ROLE NAME`. See [[Models and Routing]].

| Profile | Provider | Model |
|---|---|---|
| `haiku` | anthropic | Claude Haiku |
| `sonnet` | anthropic | Claude Sonnet |
| `opus` | anthropic | Claude Opus |
| `gpt-sol` | openai | GPT |
| `gemini-flash` | google | Gemini Flash |

Each profile has these fields:

| Field | What it does |
|---|---|
| `label` | Name Kit uses when it mentions this model. |
| `provider` | Who runs it. anthropic, openai and google need an API key in Kit's secrets folder; ollama runs on this machine. |
| `model` | The provider's model id. |
| `effort` | How hard the model thinks before answering. Higher costs more. |
| `max_tokens` | Longest answer, thinking included, in tokens. |
| `web_search` | Let the model search the web (the provider's own search). |
| `input_usd_per_mtok` | Price per million input tokens. |
| `cached_input_usd_per_mtok` | Price per million input tokens read from the prompt cache. |
| `output_usd_per_mtok` | Price per million output tokens, thinking included. |
| `search_usd_per_k` | Price per 1,000 web searches. |

## cloud

The monthly budget for cloud models. See [[Models and Routing#The budget]].

| Setting | Default | What it does |
|---|---|---|
| `monthly_cap_usd` | `40.0` | Kit stops using cloud models once this month's spend reaches this. |
| `reserve_usd` | `3.0` | As the budget runs low, cloud calls give way in order, each this much sooner than the last: evals first, then fact checks and key moments, then chat. Kit's nightly reflection always has the last of it. 0 treats them all the same. |
| `stream` | on | A Claude answer comes in as it's written, so Kit starts saying the first words (in the answer's mood) while the rest is still on its way. Goodbyes are still checked whole first. Off: each answer arrives in one piece. |

## nas

The NAS: the notes vault (the one place Kit may write) and shares he may only read. See [[Notes on the NAS]].

| Setting | Default | What it does |
|---|---|---|
| `read_only_shares` | none | Shares Kit may read but never change, by name. A UNC path on Windows (\\NAS\photo) or a mount point on Linux (/mnt/nas/photo). |
| `vault` | empty | The Obsidian vault folder, the only place on the NAS Kit may write. |
| `notes_folder` | empty | Where in the vault Kit saves notes Dan asks for, e.g. 'Inbox'. Empty for the vault's top level. |

## persona

Who Kit is and who he's with. See [[Who Kit Is]].

| Setting | Default | What it does |
|---|---|---|
| `name` | `Kit` | The assistant's name. |
| `owner` | `Dan` | Who Kit works for. |
| `backstory` | built in | Who Kit is, in a sentence or two. |
| `traits` | built in | Three to five core traits. |
| `speech` | built in | How Kit talks. |
| `location` | empty | Where the owner is, for weather and local searches, as 'city, state', e.g. Richmond, NSW. |
| `country` | empty | The owner's country as a two-letter code, e.g. AU. |
| `timezone` | empty | The owner's time zone, e.g. Australia/Sydney. |
| `knows` | built in | What Kit knows about the owner. |
| `rules` | built in | Rules Kit always follows. {owner} stands for the owner's name. |
| `examples` | built in | Sample exchanges. Small models keep character best with a few of these. |

## brain

The brain's address and how conversations start and end. See [[Brain]].

| Setting | Default | What it does |
|---|---|---|
| `host` | `127.0.0.1` | Address the brain listens on. 127.0.0.1 is this PC only; 0.0.0.0 lets the home network and Tailscale in. |
| `port` | `8600` | Port for the chat page and API. |
| `new_chat_after_minutes` | `120` | Start a fresh conversation when you come back after this long quiet (the old one stays in memory). 0 never does. |
| `new_topic_below` | `0.45` | Start fresh when a message's meaning is this far from your last few (similarity below this, 0 to 1). 0 never does. Short or 'that/it' messages never count as a new topic. |
| `history_messages` | `20` | Recent messages Kit sees each turn. |

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
| `weight_floor` | `0.3` | Among relevant memories, the ones that matter more to your life and the ones recalled lately come first; this is the least an old, small one counts (0 to 1). 1 weighs them all the same. |
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
| `sleep_after_minutes` | `10` | Kit dozes off after you've been away this long. |
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
| `bedtime` | `22:30` | When Kit starts nudging you toward bed (with nudges on). |
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
| `confidence` | `0.4` | How sure the detector must be before something counts. |
| `forget_after_s` | `3.0` | Seconds out of view before someone or something has left. |
| `report_every_s` | `1.0` | How often the eyes tell the brain what they see. |
| `faces` | on | Read faces: where each person is looking and their expression. |
| `hands` | on | Read hand gestures: thumbs up, open palm, a wave. |
| `poses` | `1` | How many people to read body pose for (each adds about 13 ms a frame). 0 turns it off. |
| `recognise` | on | Tell people apart by their faces, once they've been introduced with `kit eyes enrol NAME`. Kit keeps numbers worked out from a face, never pictures. |
| `match` | `0.4` | How alike a face must be to someone Kit knows to count as them. Higher is stricter: fewer mix-ups, but more 'someone I don't know'. |

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
| `mood_tags` | chatterbox-turbo: a sound that opens a reply in that emotion, such as [sigh] or [chuckle]. |
| `cuda_graph` | chatterbox-turbo on a graphics card: record its token loop as a CUDA graph, about 2.4 times faster with the same voice. Off: Chatterbox's own loop. On by default. See [[Voice#Faster on a graphics card]]. |

## face

How he looks. See [[Face]].

| Setting | Default | What it does |
|---|---|---|
| `character` | `retro` | Which character Kit is: how he looks and moves in the desk app, home_app and on his robots. Retro is the original glowing pill eyes; switch back any time. |
| `hot_c` | `35.0` | When you ask about the weather, a dry day this hot or hotter (°C) shows as a hot day on his face: the sun beating down and him sweating. |
| `pack_folder` | empty | A folder holding a 3D face pack (face.json and the .glb) to use for a 3D character instead of the one built into Kit, e.g. the pack folder your Blender project writes. Each rebuild shows on the desk within seconds. Empty: built in. |
