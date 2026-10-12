---
tags: [guide, topic/phone]
aliases: [Phone phase 0, Pairing a phone]
summary: Test the brain's side of the phone app before there is an app - pairing from the app with a token of its own, saying hello, history pages, messages written earlier or said aloud, and several PCs.
related: ["[[Phone App]]", "[[Bodies]]", "[[API]]"]
---

# Phone stage 0: pairing

Up: [[Home]] · Guides

This stage gets the brain ready for the [[Phone App]]: a phone pairs with a
token of its own, says hello with what it can do, scrolls back through the
whole history, and can send messages that waited or were said out loud.
There's no app yet, so these checks use `curl` from any machine on your
tailnet.

## 1. Update and restart Kit

Update as in [[Updating Kit]]. `pip install -e .` adds the `qrcode` package,
which draws the pairing code in the terminal. Nothing else is needed.

## 2. Pair a pretend phone

The app will do this itself from Kit's address and token. Do what it does,
with Kit's token from the desk app's **This PC** page (**Copy**):

```
curl -X POST -H "Authorization: Bearer KIT_TOKEN" -H "Content-Type: application/json" -d '{"name":"phone"}' http://ADDRESS:8600/api/devices/pair
```

It answers with the phone's own `token`; call it `PHONE` below. (On the
server, `kit pair phone` does the same and shows it as a QR code.)

## 3. Test before moving on

- [ ] **The phone's token works:**
  `curl -H "Authorization: Bearer PHONE" http://ADDRESS:8600/api/life`
  answers with his mood.
- [ ] **Hello:** `curl -X POST -H "Authorization: Bearer PHONE" -H "Content-Type: application/json" -d '{"kind":"phone","abilities":["screen","speaker","notify"]}' http://ADDRESS:8600/api/bodies/hello`
  answers with `features` (`chat: 2`, `messages: 2`, and `voice_out` while his
  voice is on) and a `face` page of `/face/?app=phone`.
- [ ] **Kit knows it's the phone:** send `{"text":"hi from my phone","channel":"phone"}`
  to `/api/chat` with the phone's token. He answers short, and
  `/api/bodies` shows the phone with a `last_used` time.
- [ ] **A message that waited:** send `{"text":"remind me about the bins","channel":"phone","sent_at":"TIME"}`
  with `TIME` half an hour ago (like `2026-10-12T07:40:00+08:00`). His answer
  treats it as said earlier.
- [ ] **Scrolling back:** `/api/messages` now has an `id` on each message;
  `/api/messages?before=ID&limit=20` gives the 20 before it, even from before
  a new chat.
- [ ] **The phone can't pair others:** the pair call above with the phone's
  token answers `403`.
- [ ] **Two PCs:** with the desk app on two PCs, lock one. `/api/pc/context`
  names the other as `host`, Kit doesn't think you've gone, and
  `kit life poke` is said out loud only on the PC you're using (once both desk
  apps have updated to this version).
- [ ] **Forgetting the phone:** `kit devices forget phone`, then the first
  check answers `401`. The desk app still works.

## If something's off

- **`401` with the phone's token:** it was paired again (which replaces the
  token) or forgotten. `kit devices` lists what's paired; pair it again.
- **`403` when pairing:** that was the phone's token; pairing needs Kit's
  own token.
- **`kit pair` says Tailscale isn't up:** start it (`sudo tailscale up`) or
  give the address with `--address`.
- **No QR code, just the line:** the `qrcode` package is missing; run
  `pip install -e .` in Kit's folder.
