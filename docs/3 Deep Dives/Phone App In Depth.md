---
tags: [deep-dive, topic/phone, topic/releases]
aliases: [Android app in depth, Phone app builds, Kit for Android builds]
summary: Inside Kit for Android - where its code lives, the plain-Kotlin core and the app around it, how chat, the outbox and his face work, and how GitHub builds, signs, publishes and updates it.
related: ["[[Phone App]]", "[[Phone Stage 1 - Pocket Kit]]", "[[Face In Depth]]", "[[Desk App Builds and Updates]]"]
---

# Kit for Android in depth

Up: [[Home]] · Deep dives · [[Phone App]]

Kit for Android is a thin app: the thinking, memory and voice stay on Kit's
server, and the phone talks to the brain over Tailscale like the desk app does.
What it does is in [[Phone App]]; how to test it is in
[[Phone Stage 1 - Pocket Kit]]. This page covers how it's built.

## Where it lives

| Path | What it is |
|---|---|
| `android/core/` | Plain Kotlin, no Android in it: talking to Kit, the conversation and outbox, the face rig, markdown, updates. Builds and tests anywhere with Java. |
| `android/app/` | The Android app: the screens (Jetpack Compose), the 3D face in a web view, the 2D painter, sealing the token, sending in the background, updating itself. |
| `android/core/src/test/` | The core's tests, and `face_reference.json`, numbers from the Python face rig. |
| `.github/workflows/android.yml` | Tells GitHub to test, build and publish the app. |
| `tests/test_android.py` | The Python side of the contract: rebuilds and checks `face_reference.json`. |

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

## Pairing and the token

See [[Phone App#Pairing]]. The phone's own token is sealed with a key in
Android's keystore, which never leaves the phone, and only the sealed text is
saved. Kit's shared token is used once, to pair, and isn't kept.

## How the app is built and published

GitHub builds it (`.github/workflows/android.yml`) on every pull request and
merge to main that touches `android/` or the character sheets:

1. The core's tests run.
2. The app is built and signed with Kit's signing key from the repo's secrets.
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
> - `android/app/src/main/kotlin/io/github/senitage/kit/Kit.kt`: the app's side of Kit, wiring it all together.
> - `android/app/src/main/kotlin/io/github/senitage/kit/ui/`: the screens, the face and the 2D painter.
