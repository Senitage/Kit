---
tags: [guide, topic/bodies, topic/pod]
aliases: [Build the Pod, Pod build guide, Print the Pod]
summary: Print, test, assemble, wire and program the Pod, then link him to Kit's brain over Wi-Fi, with a picture for every assembly step.
related: ["[[The Pod]]", "[[Pod In Depth]]", "[[Bodies]]"]
---

# Building the Pod

Up: [[Home]] · Guides · [[The Pod]]

From a reel of filament and a bag of parts to Kit on the desk, turning to
look at you. Print three small test pieces first, bench-test the screen and
servos before anything is boxed up, then assemble, upload and link him to
Kit. How it all works is in [[Pod In Depth]].

![[pod-v2-views.jpg]]

## 1. What you need

| Parts | |
|---|---|
| ESP32-WROOM-32 dev board | with a USB data cable |
| 1.5" SSD1351 colour OLED, 128 x 128 | the 7-pin SPI board |
| 2 x SG90 servos | with their horns and screws |
| Jumper wires and a short wire for the pat pad | |
| Screws | 4 x M2 x 4 (screws face only), 4 x M3 x 10, 3 x M3 x 16, 3 x M3 x 8 countersunk |
| Filament | PLA: white, black, grey, dark grey and a little orange (one colour and paint works too) |

| Software | |
|---|---|
| Arduino app (2.x) | with **esp32** by Espressif Systems in Boards Manager (if it isn't listed, add `https://espressif.github.io/arduino-esp32/package_esp32_index.json` under Preferences > Additional boards manager URLs) |
| Libraries (Library Manager) | **Adafruit SSD1351 library**, **Adafruit GFX Library**, **ESP32Servo** |
| Python with CadQuery (optional) | only to make or change the print files: `pip install cadquery` |

## 2. Print the parts

Make the print files from the code (they aren't kept in the repo), in
`pod/cad`:

```
pip install cadquery
python3 kit_pod_v2.py          # one STL per part, already laid the way it prints, plus STEP files
python3 kit_pod_v2.py check    # reports any parts that hit, head level and nodded fully up and down
```

`kit_pod_v2_assembly.step` opens in Fusion 360 with every part in place.

**Test pieces first.** These three check the fits that depend on your parts:

1. `face`: screw the screen onto its four posts (M2: the board's holes are
   2 mm). The picture should sit in the middle of the square window.
2. `top`: the turn servo drops into its cutout and its tab holes line up.
3. `neck`: the servo's cross horn presses into the pocket underneath, and the
   single horn into the pocket on the right arm. The pockets are drawn for a
   36 mm cross horn and a 22 mm single horn with 0.5 mm to spare; if yours
   differ, change `horn_double_len` and `horn_single_len` in `kit_pod_v2.py`.
   The two arms stand on a bar-shaped collar across the top of the round
   base, with a 45° underside, so they print as one piece with it and don't
   snap off at the root.

Then print the rest:

| Part | Colour | Lay it | Supports |
|---|---|---|---|
| head | white | back opening down | yes, tree supports |
| cover | white | flat side down | none |
| face (screws) or face_pins | black | front down | none |
| ear x 2 | orange | flat side down | none |
| neck | dark grey | disc down | touching the bed only |
| cap | white | as laid | none |
| top | grey | as laid | none |
| body | white | open bottom down | none |
| base | grey | as laid | none |
| foot x 4 | dark grey | as laid | none |

> [!TIP] Settings (Ender 3 V2, PLA)
> 0.2 mm layers (0.16 mm for the head, body and cap for smoother curves),
> 3 walls, 4 top and bottom layers, 15-20% gyroid infill, a brim on the head
> and body. Everything fits the 220 x 220 bed.

The body's three screw bosses for the base are joined to its wall by a web,
so they print as part of the body rather than as loose towers.

## 3. Wire it and test on the bench

Wire the screen and servos to the ESP32 before anything goes in the body, so
a bad wire is easy to find.

![[Pod In Depth#Wiring]]

1. Open `pod/firmware/kit_pod_screen_test/kit_pod_screen_test.ino`. Board:
   **ESP32 Dev Module**, Port: the USB one. Upload (hold **BOOT** while it says
   "Connecting..."). The screen shows red, green and blue, then a pair of
   eyes blinking and glancing.
2. Open `pod/firmware/kit_pod_servo_test/kit_pod_servo_test.ino` and upload it
   with the servo red wires unplugged, then plug them back in. Both servos go to
   centre, then the turn servo looks left and right and the tilt servo nods.

## 4. Put it together

Wires run from the head down through the neck slot and the curved slot in
the plate.

![[pod-step-01.jpg|420]]
![[pod-step-02.jpg|420]]
![[pod-step-03.jpg|420]]
![[pod-step-04.jpg|420]]
![[pod-step-05.jpg|420]]

> [!NOTE] Step 5
> The head goes on from behind, level, not down from above: the arms slide in
> through the open ends of the floor slots and the pin runs forward along the
> channel in its bracket. At the end the head settles 2 mm so the pin sits up
> in its round seat, and it can't slide back out.

![[pod-step-06.jpg|420]]

> [!NOTE] Step 6
> There's 4.5 mm to slide the tilt servo across into the horn. Push it right
> over toward the pin side before lowering it in.

![[pod-step-07.jpg|420]]

Once the horn screw is in, the horn is trapped between the shaft and the arm,
so the head can't come off.

![[pod-step-08.jpg|420]]

Two ways to hold the screen; print both and pick:

![[pod-face-options.jpg]]

![[pod-step-09.jpg|420]]
![[pod-step-10.jpg|420]]

## 5. Put Kit's program on (USB, once)

1. In `pod/firmware/kit_pod_face/`, copy `wifi_settings.example.h` to
   `wifi_settings.h` and fill in your Wi-Fi name and password. The upload
   password can stay `kitpod`.
2. Copy `kit_server.example.h` to `kit_server.h`. Leave it empty for now: he
   runs on his own until step 7.
3. Open `kit_pod_face.ino` (keep all the files in its folder). Board **ESP32
   Dev Module**, Partition Scheme **Default 4MB with spiffs** (needed for
   Wi-Fi uploads), Port: the USB one.
4. Unplug the servo red wires, hold **BOOT** during "Connecting...", upload,
   then plug the red wires back in.
5. Open the Serial Monitor at 115200. After a few seconds it says
   `On Wi-Fi as kit-pod (...)`. Type `help` to see what he can do.

### Set up the neck

The Pod serves a servo tuning page. Open `http://kit-pod.local` in a browser
on the PC or a phone (or the address after "Servo tuning page:" in the
Serial Monitor).

1. **Fit the horns.** Press "Both servos to 90° and hold". Push the neck onto
   the turn servo so Kit faces straight ahead, and slide the tilt servo onto
   its horn with the head level. If they're already on, take them off and
   refit them now.
2. **Centre.** A horn only goes on a whole tooth at a time, so he'll be a few
   degrees out. Use the Centre −1 and +1 buttons on Turn until he faces
   straight ahead, and on Tilt until his head is level.
3. **Range.** Press "One end" and "Other end" on each. Nothing should touch.
   To find the real limit, tick Free movement and nudge 1° at a time until the
   head just touches, then set Range a couple of degrees less.
4. **Direction.** Under "Check with Kit", press Look left, right, up and down.
   His eyes move first and the head should follow the same way. If it goes the
   other way, tick Flip direction for that servo and try again.
5. **Save in the Pod.** The settings stay through restarts and new uploads.

![[pod-servo-tuning.png|480]]

> [!WARNING] Keep your secrets out of the repo
> `wifi_settings.h` and `kit_server.h` are in `.gitignore`. Never rename them
> or paste their contents into the `.example.h` files.

## 6. Every upload after that (Wi-Fi)

**Tools > Port > kit-pod at 192.168...**, then **Upload**, and type the upload
password. His face shows a progress bar, the servos go limp, then he restarts.
No cable, no buttons. If the port doesn't show, restart the Arduino app.

## 7. Link him to Kit

So far he runs on his own. Linking him means the brain's body feed, which is
pull request #36; until that's merged, he says "Can't reach Kit" and carries
on by himself.

1. **Let the home network reach Kit.** On the server, Kit must listen beyond
   the PC itself (the desk app on another PC needs this too):
   ```
   kit config set brain.host 0.0.0.0
   sudo systemctl restart kit
   ```
2. **Pass port 8600 through Windows to WSL.** In an admin PowerShell on the
   Windows PC, in the repo's `pod\network` folder:
   ```powershell
   .\kit-port-forward.ps1 -Install
   New-NetFirewallRule -DisplayName "Kit (port 8600)" -Direction Inbound -Protocol TCP -LocalPort 8600 -Action Allow -Profile Private
   ```
   The first sets up the forward now and at every logon (WSL's address can
   change when the PC restarts). The second lets the home network in. The home
   network should be set to **Private** in Windows.
3. **Find the PC's home address.** `ipconfig` in PowerShell: the IPv4 Address
   of the Wi-Fi or Ethernet adapter, like `192.168.1.20`. Check it from a phone
   on the home Wi-Fi: `http://192.168.1.20:8600/api/health` should answer.
4. **Tell the Pod.** In `kit_server.h`:
   ```c
   #define KIT_URL "http://192.168.1.20:8600"
   #define KIT_TOKEN "the token from kit token on the server"
   ```
   Upload over Wi-Fi. The Serial Monitor says "Linked to Kit's brain".

> [!TIP] Give the PC a fixed address
> Reserve the PC's address in your router (DHCP reservation), so `KIT_URL`
> stays right after the router restarts.

## 8. Test before moving on

- [ ] **Screen:** the screen test shows red, green and blue in the right
      colours, then blinking eyes.
- [ ] **Servos:** the servo test turns left and right and nods, both from
      centre, without hitting anything.
- [ ] **Face:** after the upload he perks up, blinks and looks about. `tour`
      shows all 20 moods.
- [ ] **Facing forward:** at rest he faces straight ahead and level, and
      turns and nods the same way as his eyes. If not, fix it on the servo
      tuning page (step 5, "Set up the neck") and save.
- [ ] **Calm neck:** over a few idle minutes the head mostly stays still while
      the eyes dart about; now and then he glances round.
- [ ] **Pats:** one pat gives a wiggle; three quick pats and he laughs.
- [ ] **On his own:** left alone with no `KIT_URL` he dozes off after 3
      minutes; a pat wakes him.
- [ ] **Wi-Fi upload:** an upload over Wi-Fi shows the progress bar and he
      restarts.
- [ ] **Linked:** with #36 on the server, the Serial Monitor says "Linked to
      Kit's brain". Chat to Kit at the desk: the Pod looks thoughtful, then
      shows the reply's emotion while his mouth moves.
- [ ] **Sleep:** when Kit sleeps, the Pod puts his head down and shuts his eyes.
- [ ] **A pat reaches Kit:** pat him, then ask Kit how he's feeling.
- [ ] **Eyes:** with `kit eyes` running, walking in front of the camera makes
      the Pod turn to you.

## If something's off

- **The screen stays black:** check VCC is on 3V3 (not 5 V) and DIN/CLK/CS/DC/RST
  against the wiring table. Run the screen test again.
- **The upload fails over USB:** unplug the servo red wires and hold **BOOT**
  during "Connecting...". If no port shows, install the board's USB driver
  (CP210x or CH340).
- **Wi-Fi upload: "No response from device" after "Authenticating... OK":**
  - the screen didn't change: the partition scheme has no room for a Wi-Fi
    upload. Set **Default 4MB with spiffs** and upload once over USB.
  - the screen flicks to the update screen and straight back: the upload's
    call back is going the wrong way. With Tailscale on the PC, untick **Use
    Tailscale subnets** in its tray menu > Preferences.
  - the bar stays at 0%: the Pod can't reach the PC. Set the network to
    Private and allow `espota.exe` through Windows Firewall.
- **"Can't reach Kit" in the Serial Monitor:** check `/api/health` from a phone
  (step 7.3), run `kit-port-forward.ps1` again, and check the brain has #36.
- **"Kit says the token is wrong":** copy `kit token` again into `KIT_TOKEN`.
- **He resets or twitches when the head moves:** the servos run off the USB's
  5 V, so a weak charger or long thin cable can dip. Try a good 5 V 2 A
  charger and a short cable.
- **He doesn't face straight ahead, or turns the wrong way:** set it on the
  servo tuning page (step 5, "Set up the neck") and press Save in the Pod.
- **The head rubs or catches:** `python3 kit_pod_v2.py check` says whether the
  model itself hits; if it's clear, look for a blob or leftover brim on the
  print.
