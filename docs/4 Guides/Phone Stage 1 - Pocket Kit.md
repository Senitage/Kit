---
tags: [guide, topic/phone]
aliases: [Phone phase 1, Pocket Kit, Installing Kit for Android]
summary: Install Kit for Android, pair it by typing Kit's address and token, and test chatting from the phone with his face on top, messages that wait while he's out of reach, and updates.
related: ["[[Phone App]]", "[[Phone App In Depth]]", "[[Phone Stage 0 - Pairing]]"]
---

# Phone stage 1: Pocket Kit

Up: [[Home]] · Guides

The first Kit for Android you can install: his face at the top (3D, or Kit 2D),
the whole conversation with Kit knowing you're on your phone, and messages that
wait while he's out of reach. Finish [[Phone Stage 0 - Pairing]] first: the
brain needs it. How it works is in [[Phone App]] and [[Phone App In Depth]].

## 1. Update and restart Kit

Update as in [[Updating Kit]]. Nothing else is needed on the server.

## 2. Give GitHub Kit's signing key (once)

Android only lets an app update itself with the same signing key, so GitHub
signs every build with Kit's key. It lives only in the repo's secrets. On
GitHub, open the repo's **Settings > Secrets and variables > Actions** and add
two repository secrets:

| Name | Value |
|---|---|
| `KIT_ANDROID_KEYSTORE` | The keystore, as base64 text |
| `KIT_ANDROID_KEYSTORE_PASSWORD` | Its password |

Then re-run the latest **Android app** run (Actions tab), so it builds with the
key and publishes. Keep a copy of the keystore and password somewhere safe:
without them, the next version can't update the installed app.

## 3. Install it

1. Install **Tailscale** on the phone, sign in, and set it to always on.
2. On the phone, open the repo's **Releases** page on GitHub and find the newest
   **Kit for Android** (or the test build for a pull request), then tap its
   `.apk`.
3. Android asks to allow your browser to install apps: allow it, then install.

## 4. Pair it

1. On the PC, open the desk app's **This PC** page and tap **Copy** next to the
   token.
2. Get the token to the phone (any way you like: a note to yourself, or
   Windows' phone link).
3. In the app, type Kit's address (his Tailscale name or address, the same as
   the desk app's), paste the token, and tap **Pair**.

Or, on the server, run `kit pair phone` and scan the code with the phone's
camera: it opens Kit and asks to pair.

## 5. Test before moving on

- [ ] **Paired:** the chat opens with Kit's face at the top and your recent
  conversation underneath, including what you said at the desk (marked
  "at the desk").
- [ ] **He knows it's the phone:** say "where am I talking to you from?". He
  says your phone, and keeps it short.
- [ ] **His face acts it out:** his face reacts as he answers, and his words
  show in his bubble under his face. Scroll up and his face shrinks into the
  top bar.
- [ ] **3D and 2D:** with his 3D face set (`face.character kit3d`), the 3D face
  shows after a moment. Menu > **Show his 2D face** swaps to Kit 2D.
- [ ] **Boop and pat:** tap his face for a boop, hold for a pat. The phone buzzes.
- [ ] **Out of reach:** turn Tailscale off. His face goes grey and the banner
  says Tailscale is off, with a button to open it.
- [ ] **A message that waits:** with Tailscale still off, send "remind me about
  the bins". It shows "waiting to send". Wait a few minutes, turn Tailscale on:
  it sends by itself, and Kit treats it as said earlier.
- [ ] **Closed app:** turn Tailscale off, send a message, close the app, turn
  Tailscale on. Open Kit on the PC: the message arrived without the app open.
- [ ] **Scrolling back:** scroll up past the start of the chat; older messages
  load, back past new chats.
- [ ] **Pipe-ups:** `kit life poke` with the app open: his line shows in the
  chat and his face perks up. (Notifications with the app closed come in phase 2.)
- [ ] **Updates:** after the next merge to main, open the app: a banner offers
  the new version, and **Update** installs it over the top.
- [ ] **Unpair:** Menu > **About this phone** > **Unpair**. `kit devices` no
  longer lists the phone.

## If something's off

- **"Can't reach Kit" with Tailscale on:** check the address is the one the
  desk app uses, and that Kit's PC is on. Try his Tailscale address instead of
  his name.
- **"Kit didn't accept that token":** copy it again from the desk app; a token
  pasted with a space or missing a character fails.
- **No 3D face, only Kit 2D:** Kit's character has no 3D look, or the phone's
  web view can't draw it. Kit 2D is the same Kit.
- **"App not installed" on update:** the new build was signed with a different
  key (the secrets changed or were missing). Uninstall and install again, then
  pair again.
- **No update offered:** the build wasn't published because the signing
  secrets are missing; the Actions run says so.
