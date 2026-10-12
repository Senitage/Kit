---
tags: [deep-dive, topic/phone, topic/releases]
aliases: [Android app in depth, Phone app builds, Kit for Android builds]
summary: Inside Kit for Android - where its code lives, the plain-Kotlin core and the app around it, how chat, the outbox and his face work, how nudges and notifications reach a closed app, what the phone senses, the settings page drawn from his schema, the widget and tile, and how GitHub builds, signs, publishes and updates it.
related: ["[[Phone App]]", "[[Phone Stage 1 - Pocket Kit]]", "[[Phone Stage 2 - He's With You]]", "[[Face In Depth]]", "[[Inner Life In Depth]]", "[[Desk App Builds and Updates]]"]
---

# Kit for Android in depth

Up: [[Home]] · Deep dives · [[Phone App]]

Kit for Android is a thin app: the thinking, memory and voice stay on Kit's
server, and the phone talks to the brain over Tailscale like the desk app does.
What it does is in [[Phone App]]; how to test it is in
[[Phone Stage 1 - Pocket Kit]] and [[Phone Stage 2 - He's With You]]. This page
covers how it's built.

## Where it lives

| Path | What it is |
|---|---|
| `android/core/` | Plain Kotlin, no Android in it: talking to Kit, the conversation and outbox, the face rig, markdown, updates, which pipe-ups to notify, home or out, the settings form. Builds and tests anywhere with Java. |
| `android/app/` | The Android app: the screens (Jetpack Compose), the 3D face in a web view, the 2D painter, sealing the token, sending in the background, nudges and notifications, the phone's senses, the widget and tile, updating itself. |
| `android/core/src/test/` | The core's tests, `face_reference.json` (numbers from the Python face rig) and `settings_schema.json` (a copy of his settings schema). |
| `.github/workflows/android.yml` | Tells GitHub to test, build and publish the app, with the Firebase ids from the repo's variables. |
| `tests/test_android.py` | The Python side of the contract: rebuilds and checks `face_reference.json` and `settings_schema.json`. |
| `src/kit/push.py`, `src/kit/phone_context.py` | The brain's side: nudging the phone, and what the phone tells him. |

It isn't part of the Python package and ruff doesn't look at it. Kit never
depends on it: the app only uses the brain's API ([[API]]).

> [!info] Why two parts
> The `core` is most of the app's logic and needs only Java to build, so it's
> tested on every change, even on a machine without Android's tools. The `app`
> is the screens and the Android-only parts around it.

## Talking to Kit

`KitClient` (in `android/core/src/main/kotlin/io/github/senitage/kit/core/KitClient.kt`)
makes the calls: health, pairing, the hello, messages, chat, life and its
events, and the character sheet. Every answer is read with unknown fields
skipped, and every field has a default, so a newer brain doesn't break an older
app. Chat events the app doesn't know are skipped too ([[API#Talking]]).

A failed call is one of a few kinds, each explained in words on screen:

| Kind | Means | The app says |
|---|---|---|
| Unreachable | Nothing answered | Tailscale is off, or his PC may be off or asleep |
| Bad token | Kit doesn't know this phone's token | Pair again |
| Not allowed | A device token tried to pair | Use Kit's own token |
| Broken | The answer started, then the line dropped | His answer is saved and shows once he's back |

## The conversation and the outbox

`Conversation` keeps three things and shows them as one chat:

1. **The history**, from `/api/messages`: the truth. It loads the latest page
   across the whole history, catches up with `after=` and scrolls back with
   `before=`. The latest 300 messages are kept on the phone, so the chat is
   there to read even when Kit isn't.
2. **The answer streaming in now**, as live lines. When the turn ends, the
   history catches up and the live lines give way to the saved ones. Notes
   ("Remembered: ...") stay, because Kit doesn't save those.
3. **The outbox**: messages typed on the phone that haven't reached Kit. They
   are saved on the phone straight away and sent one at a time while Kit can be
   reached. A message that waited more than 30 seconds goes with `sent_at`, the
   time it was written, so Kit knows it's old news. A message counts as sent as
   soon as the brain accepts it, so a dropped line mid-answer never sends it
   twice. When the app is closed with messages waiting, Android sends them once
   there's a network (WorkManager).

Every message goes on the `phone` channel with this phone's device name as its
`body`, so Kit knows he's on the phone and which body it came through
([[Brain#Where you're talking from]]).

## His face

The face at the top is one `Face`, a Kotlin port of the desk's face rig
(`kit.face.rig`), moved by a `Director` that hears the chat, his life events,
being out of reach, and taps. Then one of two things draws it:

- **3D**, when Kit's character has a 3D look for the phone: the brain's face
  page (`/face/?app=phone`) in a web view, driven through its `kit` API the way
  the desk app drives it (`Mirror` sends only what changed). The page, model
  and pack come from the brain and reload themselves when they change. The
  brain sends each face file with an ETag, so the phone keeps the model it has
  and only downloads it again when it changes.
- **2D**, the glow face drawn natively, a port of the desk's Glow painter: Kit
  2D's screen, eyes, brows, mouth and blush, or a 3D character's 2D fallback. It
  shows while the 3D page loads, when Kit has no 3D look, and when you pick
  "Show his 2D face".

The port reads the same character sheet the brain serves at `/api/face`, so the
phone moves him with the same numbers as the desk. `CharacterTest` checks the
port against numbers made by the Python (`face_reference.json`). If a character
sheet changes, rebuild them:

```
python tests/test_android.py
```

There's no voice on the phone yet, so a reply is acted out on timing guessed
from its words, like the desk with his voice off: the emotion, each gesture a
beat before its words, and his words in his bubble.

A tap on his face is a boop (a little move and a buzz), a long press a pat (a
fond wiggle). These are only on the phone for now.

## Nudges

A closed Android app can't be reached from the brain, so the brain **nudges**
it through Firebase Cloud Messaging (`src/kit/push.py`), which is how Android
wakes apps for a message. The nudge is data only, high priority, kept for half
an hour at most, and content-free:

```json
{"kit": "pipe_up", "id": "42"}
```

Nothing Kit said goes through Google. On the phone, `KitMessagingService`
hears the nudge and, within the few seconds of network the push grants, the
app fetches the messages after the last one it showed (`/api/messages?after=`)
and posts a notification for each unseen pipe-up (`newPipeUps`, cut to the
last three so a phone that was off for a week isn't buried). If that doesn't
finish in time, `CatchUpWorker` does the same once there's a network.

The brain sends a nudge from `pipe_up_now` when `phone.notify` allows it
(`away`: only while no PC is in use; `always`; `never`), at most
`phone.notify_per_hour` an hour per phone. It signs a service-account JWT
(`cryptography`) for a short-lived access token, sends the message with
Firebase's HTTP v1 API, and forgets a token Firebase says is gone
(`UNREGISTERED`), so a reinstalled app just registers again. A test nudge
(`kit nudge`, `POST /api/nudge`) sends `{"kit": "test"}`, shown as "Kit can
reach this phone".

The phone gives the brain its token on each hello (`POST
/api/devices/{name}/push`, kept with the device in `devices.json`), and takes
it back (`DELETE`) when notifications are switched off or the phone unpairs.
The brain's answer says whether it can nudge at all (`nudges`), which the
Settings tab shows.

> [!info] Firebase without a google-services file
> The app sets Firebase up by hand (`Nudges.setUp`) from four ids GitHub puts
> in the build from the repo's variables (`KIT_FIREBASE_PROJECT_ID`, `APP_ID`,
> `API_KEY`, `SENDER_ID`), so the repo holds no Firebase file and a build
> without the variables still works: `BuildConfig.FIREBASE` is false, the
> phone has no token, and `CatchUpWorker` looks in every half hour instead.
> That worker runs anyway, as the net under a lost nudge. The service-account
> file that lets the brain send lives only in his secrets folder
> ([[Phone Stage 2 - He's With You]]).

## Notifications

A pipe-up's notification (`Notifier`) is a messaging-style notification from
a person named Kit, on a high-importance channel, with two actions:

- **Reply**, an inline reply box. `ReplyReceiver` gets the words and
  `ActWorker` sends them as a normal chat turn on the `phone` channel with
  this phone as the body; the turn's reply goes back into the same
  notification under what was typed, so the exchange reads as a conversation
  there. If Kit can't be reached, the words go into the chat's outbox and the
  notification says it's waiting.
- **Quiet for an hour**, which snoozes him (`POST /api/life/snooze`) and
  clears his notifications.

Opening the app clears them too, and the app's own catch-up moves the "last
seen" mark so nothing shown in the chat is notified later. Pipe-ups while the
app is open show in the chat as before, never as notifications. On Android 13
and up the app asks for the notifications permission once, after pairing.

## What the phone senses

`PhoneSenses` works out **home or out** with no location permission: the
Settings tab's **This Wi-Fi is home** keeps a fingerprint of the current
Wi-Fi's gateway and DNS addresses (sorted, joined and hashed:
`NetworkSeen.fingerprint`), and `decidePlace` says home on that fingerprint,
out on another Wi-Fi or on mobile data, and unknown otherwise (no network, or
no home marked). The battery comes from `BatteryManager`. `PlaceTracker`
decides when a report is worth sending: a change of place, the charger coming
or going, the battery crossing 20%, and otherwise every half hour at most.
Reports go when the app comes forward, when the network changes, on every
catch-up, and when Android says the battery is low or okay or the charger
changed (`SensesReceiver`). The brain keeps the latest report per phone
(`kit.phone_context`), turns it into one line for his prompt and his
pipe-up sense of the moment, and after twelve hours says it's stale. Each
sense has a switch kept on the phone; off means the report says `unknown` or
leaves the battery out.

## The settings page from his schema

The Settings tab draws Kit's settings from `GET /api/settings/schema`, the
JSON Schema pydantic makes, the way the desk's and home_app's pages do.
`SettingsForm` (core) turns it into sections and fields with a kind each: a
switch, a choice, a whole number or a number (with its range), text, lines
(persona traits, rules) or "other", for the tables of named profiles (models,
voice engines) the phone leaves to the PC. Each change is one
`PATCH /api/settings` (`X-Changed-By: phone`), so **Undo last change** is the
brain's own undo. `SettingsFormTest` runs against a copy of the real schema
in `settings_schema.json`, which `tests/test_android.py` keeps current:

```
python tests/test_android.py
```

rebuilds it (and `face_reference.json`) whenever a setting or character sheet
changes; the Python test fails until it's done.

## The widget, the tile, sharing and the rest

- **Widget** (`widget/KitWidget.kt`, Glance): his 2D face drawn with the chat's
  painter into a bitmap, how he is (his feeling and why, or his mood, or
  "keeping quiet"), and his last line from the chat kept on the phone. It's
  redrawn when the app goes to the background and after every catch-up, when
  something changed. A tap opens the app.
- **Quick Settings tile** (`QuietTile`): active while he's snoozed, with until
  when; a tap snoozes him for an hour or lets him speak, through `ActWorker`.
- **Share to Kit**: the app takes `ACTION_SEND` text, which lands in the chat
  box with anything already typed.
- **Shortcuts** on the app icon: new chat, and quiet for an hour.
- **Shake**: the accelerometer, while the app is open; a shake plays his
  `startle` gesture with a buzz.
- **Battery saver**: while it's on, `facePage()` is null and his face stays 2D.
- **Tabs**: one `Scaffold` with a navigation bar that hides while the keyboard
  is up; the chat pads for the navigation bar and then the keyboard.

## Pairing and the token

See [[Phone App#Pairing]]. The phone's own token is sealed with a key in
Android's keystore, which never leaves the phone, and only the sealed text is
saved. Kit's shared token is used once, to pair, and isn't kept.

## How the app is built and published

GitHub builds it (`.github/workflows/android.yml`) on every pull request and
merge to main that touches `android/` or the character sheets:

1. The core's tests run.
2. The app is built with the Firebase ids from the repo's variables and signed
   with Kit's signing key from the repo's secrets.
3. The APK is attached to the run as an artifact.
4. A merge to main is published as a release tagged `android-v0.1.<build>`. A
   pull request's build is published as a pre-release test build, replacing
   that pull request's last one.

> [!warning] The signing key
> Android only installs an update signed with the same key as the app already
> installed. The key lives only in the repo's secrets: `KIT_ANDROID_KEYSTORE`
> (the keystore, base64) and `KIT_ANDROID_KEYSTORE_PASSWORD`. Without them the
> build still runs, but it isn't published, because it couldn't update an
> installed Kit. Losing the key means uninstalling and installing again.

## How updates reach the phone

The app checks the repo's releases when it opens (at most every six hours, or
from the menu) for an `android-v...` release newer than its own build. If there
is one, a banner offers it; **Update** downloads it and hands it to Android to
install. The first time, Android asks you to allow Kit to install apps. A test
build only offers newer test builds and releases.

## Building it yourself

Only needed to change the app. With Java 17:

```
cd android
./gradlew -p core test
```

builds and tests the core. The whole app needs Android's SDK too (Android
Studio has it), then `./gradlew assembleDebug`.

> [!under-the-hood]- Under the hood: the code
> - `android/core/src/main/kotlin/io/github/senitage/kit/core/Conversation.kt`: history, live turns and the outbox.
> - `android/core/src/main/kotlin/io/github/senitage/kit/core/Reach.kt`: is Kit there, and his life events.
> - `android/core/src/main/kotlin/io/github/senitage/kit/core/Face.kt` and `Character.kt`: the face rig and the sheet.
> - `android/core/src/main/kotlin/io/github/senitage/kit/core/Director.kt`: acting him out, and the 3D page's calls.
> - `android/core/src/main/kotlin/io/github/senitage/kit/core/Notify.kt`, `Place.kt`, `SettingsForm.kt`, `Models.kt`: which pipe-ups to notify, home or out, the settings form, and his notebook, memory and settings as the phone reads them.
> - `android/app/src/main/kotlin/io/github/senitage/kit/Kit.kt`: the app's side of Kit, wiring it all together, with the catch-up.
> - `android/app/src/main/kotlin/io/github/senitage/kit/Nudges.kt`, `Notifier.kt`, `CatchUpWorker.kt`, `ActWorker.kt`: Firebase, notifications and the background work.
> - `android/app/src/main/kotlin/io/github/senitage/kit/PhoneSenses.kt`, `Shaker.kt`, `QuietTile.kt`, `widget/`: the senses, the shake, the tile and the widget.
> - `android/app/src/main/kotlin/io/github/senitage/kit/ui/`: the screens (chat, Kit, Memory, Settings), the face and the 2D painter.
> - `src/kit/push.py` and `src/kit/phone_context.py`: the brain's side.
