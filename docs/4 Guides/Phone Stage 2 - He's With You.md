---
tags: [guide, topic/phone]
aliases: [Phone phase 2, Phone notifications, Setting up Firebase for Kit, He's with you]
summary: Set up Kit's nudges (Firebase) so his pipe-ups reach the phone as notifications you can answer, mark your home Wi-Fi so he knows home from out, and test the Kit, Memory and Settings pages, the widget, the tile and sharing to him.
related: ["[[Phone App]]", "[[Phone App In Depth]]", "[[Phone Stage 1 - Pocket Kit]]", "[[Inner Life]]"]
---

# Phone stage 2: he's with you

Up: [[Home]] · Guides

Kit for Android stops being a chat you open and becomes Kit in your pocket:
when he speaks up and the app is closed, it lands as a notification from him
that you answer in place; he knows whether you're home or out, and when your
phone's nearly flat; his Kit, Memory and Settings pages are on the phone; and
he's on the home screen as a widget. Finish [[Phone Stage 1 - Pocket Kit]]
first. How it works is in [[Phone App#He's with you]] and
[[Phone App In Depth#Nudges]].

## 1. Update and restart Kit

Update as in [[Updating Kit]]. `pip install -e .` adds the `cryptography`
package, which signs Kit's requests to Firebase. Restart Kit. Without the next
step, the phone still gets his pipe-ups, just by looking in every half hour.

## 2. Give Kit a Firebase project (once)

Firebase Cloud Messaging is how Android wakes a closed app. Kit sends it only a
nudge ("look at me"), never a word of what he said: the phone fetches that
from the brain over Tailscale. It's free.

1. At [console.firebase.google.com](https://console.firebase.google.com), add a
   project (any name, Analytics off). In it, add an **Android app** with the
   package name `io.github.senitage.kit`. Skip downloading `google-services.json`:
   Kit doesn't use it.
2. In the project's **Settings > General**, under *Your apps*, note four
   things: the **Project ID**, the **App ID** (`1:...:android:...`), the
   **Web API key** (under *Project settings*) and the **Sender ID** (in
   *Cloud Messaging*, the project number).
3. On GitHub, open the repo's **Settings > Secrets and variables > Actions >
   Variables** and add four repository variables (variables, not secrets: they
   end up in the app, which is fine; the key only identifies the project):

   | Name | Value |
   |---|---|
   | `KIT_FIREBASE_PROJECT_ID` | the project ID |
   | `KIT_FIREBASE_APP_ID` | the app ID |
   | `KIT_FIREBASE_API_KEY` | the web API key |
   | `KIT_FIREBASE_SENDER_ID` | the sender ID |

4. In the Firebase project's **Settings > Service accounts**, click **Generate
   new private key**. Put the file it downloads on Kit's server as
   `firebase_service_account.json` in his data folder's `secrets/` (see
   [[Settings and Data#The data folder]]), owner-only, or point
   `KIT_FIREBASE_SERVICE_ACCOUNT` at it. This one is a secret: it lets Kit send
   nudges and nothing else.
5. Re-run the latest **Android app** run on GitHub so the app is built with the
   project, then update the app on the phone, and restart Kit.

```
kit devices
```

lists the phone with `notifies` once the app has given Kit its push token.

## 3. Mark home

In the app's **Settings** tab, with the phone on your home Wi-Fi, tap **This
Wi-Fi is home**. Kit only ever hears "home" or "out", never a network name or a
place (what the phone keeps is a scrambled fingerprint of the network). Leave
**Tell him when I'm home or out** and **Tell him about the battery** on, or
switch off either.

## 4. Choose when he nudges

Kit's setting `phone.notify` says when a pipe-up goes to the phone: `away`
(only while no PC is in use, the default: the desk app has it otherwise),
`always`, or `never`. `phone.notify_per_hour` caps them. Change it on the
phone's Settings tab, under *Phone*, or:

```
kit config set phone.notify always
```

## 5. Test before moving on

- [ ] **Permission:** the first time the app opens after the update it asks to
  show notifications. Allow it.
- [ ] **A test nudge:** on the server, `kit nudge`. The phone shows "Kit can
  reach this phone". (Without Firebase it says so, and the rest still works
  through the half-hourly look-in; allow more time for each check below.)
- [ ] **A pipe-up as a notification:** close the app, step away from the PC
  (or set `phone.notify always`) and run `kit life poke`. A notification from
  Kit with his line arrives, with **Reply** and **Quiet for an hour**.
- [ ] **Answer in place:** tap **Reply**, type something, send. His answer
  appears in the same notification. Open the app: the exchange is in the chat.
- [ ] **One voice at a time:** with the desk app open and you at the PC (and
  `phone.notify away`), `kit life poke` shows on the desk and not on the
  phone.
- [ ] **Quiet:** tap **Quiet for an hour** on a notification, or the tile
  (Quick Settings > edit > add **Hush Kit**). `kit life` shows him snoozed; the
  Kit tab says "Keeping quiet until...". Tap again to let him speak.
- [ ] **Home and out:** with home marked, switch Wi-Fi off and ask him "am I
  home?". He says you're out, since a moment ago. The Kit tab's "What this
  phone tells him" shows the line he sees.
- [ ] **Battery:** with the phone under 20%, he knows it's nearly flat; plug
  it in and he knows it's charging.
- [ ] **The Kit tab:** how he's feeling and why, what he's up to, what's on his
  mind, his quirks and notebook. Pull down to refresh.
- [ ] **The Memory tab:** search what he remembers, teach him something and see
  it under Facts, star one to always keep it in mind, forget one. Things and
  Days show his register and day summaries.
- [ ] **The Settings tab:** his settings, drawn from the brain: flip
  `life.pipe_ups` off and on; the desk app's settings page shows the change.
  **Undo last change** puts it back.
- [ ] **Widget:** long-press the home screen, add the Kit widget. His face, how
  he is and his last line; tap opens the app. It redraws when he changes.
- [ ] **Share to him:** in any app, share some text to Kit. It lands in his chat
  box.
- [ ] **Shortcuts:** long-press the app icon: **New chat** and **Quiet for an
  hour**.
- [ ] **Shake:** shake the phone with the app open. He's startled.
- [ ] **Battery saver:** turn battery saver on. His face goes 2D until it's off.

## If something's off

- **"Kit's PC has no Firebase account yet":** the service account file isn't
  in `secrets/` (or isn't readable), or Kit hasn't been restarted since. The
  phone looks in every half hour in the meantime.
- **"This build has no push":** the app was built without the four repository
  variables. Add them and re-run the Android app build, then update.
- **No notification arrives:** check the phone allows Kit's notifications, and
  that `kit devices` shows the phone with `notifies`. Pipe-ups while a PC is in
  use stay on the desk unless `phone.notify` is `always`.
- **`kit nudge` says "no phone can be nudged":** open the app once after the
  update so it gives Kit its token.
- **"Out" while on the home Wi-Fi:** the router's addresses changed (a new
  router, or a mesh that hands out different gateways). Tap **This Wi-Fi is
  home** again.
