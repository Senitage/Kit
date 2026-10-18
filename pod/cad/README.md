# Kit Pod v2

A cute pill-head Pod built around your parts: the 1.5" OLED, two SG90 servos and the ESP32.

The model is code: `kit_pod_v2.py` (CadQuery) builds every part. The STEP and STL
files it makes aren't kept in the repo; make them with:

```
pip install cadquery
python3 kit_pod_v2.py          # writes the files below next to this one
python3 kit_pod_v2.py check    # reports anything that hits, head level and nodded fully up and down
```

- **Open in Fusion 360:** `kit_pod_v2_assembly.step` (every part in place, with the screen, servos and ESP32 as see-through reference blocks).
- **Print:** one `kit_pod_v2_<part>.stl` per part, already laid the way it prints. STEP copies of each are there too.
- **Pictures:** `render_pod.py` draws the renders and `render_steps.py` the assembly guide (`assembly/`). The docs show them: `docs/4 Guides/Building the Pod.md`.

Total height is about 132 mm.

## Parts

| Part | Colour | How to print | Size (mm) |
|---|---|---|---|
| head | white | back opening down | 68 x 56 x 43 |
| cover (back of head) | white | flat side down | 65 x 53 x 9 |
| face (black glass round the screen), screws option | black | front down | 48 x 40 x 5 |
| face_pins, the other option | black | front down | 48 x 40 x 8 |
| ear x2 | orange | flat side down | 20 x 20 x 2.4 |
| neck | dark grey | disc down | 48 x 44 x 29 |
| cap (dome on top of the body) | white | as laid | 63 x 63 x 9 |
| top (plate; its edge is the grey band) | grey | as laid | 64 x 64 x 4 |
| body | white | upright, open bottom down | 70 x 70 x 47 |
| base | grey | as laid | 67 x 67 x 11 |
| foot x4 | dark grey | as laid | 12 x 12 x 4 |

## Printing (Ender 3 V2)

Every STL is already turned the way it prints, so just drop them on the bed. Everything fits on the 220 x 220 bed.

**Settings (PLA):** 0.2 mm layers (0.16 mm for the head, body and cap if you want smoother curves), 3 walls, 4 top and bottom layers, 15-20% gyroid infill, brim on the head and body.

**Supports:**
- head: yes, tree supports. It prints with the back opening down, so the front of the head is a roof over the hollow inside.
- neck: supports touching the bed only, for the little pin on the left arm.
- everything else: none.

**Order: test pieces first.** These three are small and check the fits that depend on your measurements, before you spend hours on the big parts.
1. `face`: screw the screen onto its four posts. The picture should sit in the middle of the square window.
2. `top`: the turn servo should drop into its cutout and its tab holes should line up.
3. `neck`: the servo's cross horn should press into the pocket underneath, and the single horn into the pocket on the right arm.

If those are good, print `head`, `body`, `cap`, `base`, `cover`, then the small bits: 2 x `ear`, 4 x `foot`.

**Colours:** white for head, cover, cap and body; black for the face; grey for the top plate and base; dark grey for the neck and feet; orange for the ears. Use what you have; one colour plus paint works too.

## Screws

- 4 x M2 x 4 for the screen board (screws option; the pins option needs none)
- 4 x M3 x 10 for the back cover
- 3 x M3 x 16 for the body, plate and cap
- 3 x M3 x 8 countersunk for the base
- The screws and horns that come with the SG90s

## Putting it together

Pictures for every step: `assembly/kit_pod_v2_assembly_guide.pdf` (one PNG per step in `assembly/` too).

1. Turn servo up through the top plate; tab screws from below.
2. Sandwich the plate between body and cap with the three long screws from below.
3. Press the cross horn into the pocket under the neck (drop of glue). Push the neck onto the turn servo and fit the horn screw through the centre hole from above.
4. Press the single horn into the pocket on the inside of the horn arm (the arm on your right as Kit faces you), arm pointing down, drop of glue.
5. Hold the head behind the neck, level, and slide it forward: the arms go in through the open ends of the floor slots, and the pin on the other arm runs along the channel in its bracket, and at the end the head settles 2 mm so the pin sits up in its seat and can't slide back.
6. Drop the tilt servo in through the back of the head, pushed over toward the pin side, lower it into the U-shaped wall, then slide it across so its shaft goes into the horn. There's 4.5 mm of room for this.
7. Two tab screws into the wall, then the horn screw through the small hole below the ear on the horn side. The horn is then trapped between the shaft and the arm, so the head can't come off.
8. Screen, two options (print both and pick):
   - **screws** (`face`): glue the plate into the head, put the screen on its four posts and drive 4 x M2 x 4 screws in from the back, through the board into the blind pilot holes in the posts (they cut their own thread in the plastic). Nothing shows from the front, and the screws come out again from inside the head.
   - **pins** (`face_pins`): glue the plate in, push the screen onto the four pins, a dab of hot glue on each pin end. Hot glue peels off if the screen needs to come out.
9. Glue the ear rings into the side grooves. Back cover on with four screws.
10. ESP32 stands in the base slots, USB to the hole at the back left. Base on with three screws, feet glued in.

Wires run from the head through the neck slot and the curved slot in the plate.

## Measured

Dan's measurements (2026-10-10) are in the model:

- Screen glass sits 1.9 mm in front of the blue board (3.4 glass + board, 1.5 board).
- The lit picture is 27.2 x 27.5 mm and sits near the top of the board (gaps: top 1.7, left 8.6, right 9.2, bottom 7.8). The face plate puts the picture in the middle of the window.
- Servo shaft top is 12.2 mm above the top of the tabs.
- Servo is 20 mm from the top of its tabs to its bottom (2026-10-11).
- Servo horns, end to end: the cross horn 36 mm, the single horn 22 mm (2026-10-11). Their pockets in the neck are 0.5 mm bigger all round.
- With the single horn on, the servo is 34.2 mm from its bottom to the horn's face, against 32 without (2026-10-12): the horn stands 2.2 mm past the shaft, and the horn arm sits that much further out so the servo's tabs meet their wall.
- The screen board's fixing holes are 2 mm, so the screws face takes M2 screws (1.6 mm pilot holes) and its pins are 1.6 mm (2026-10-12).

The neck arms reach a little past the round base (the cap's opening limits its size), so they stand on a collar: a 54 mm wide bar across the top of the base, with a 45 degree underside that clears the cap's lip. It's a bar, not a ring, because the head's floor swings down to that height at the front and back on a full tilt (2026-10-13).

The pin's bracket in the head is 4 mm thick, with 7 mm of wall below the pin's channel and 6.7 mm above its seat, so it survives having its supports pulled off (2026-10-13).

The body's three base screw bosses are joined to its wall by a 7 mm web with a 45 degree gusset on top. On their own they stood 0.1 to 0.9 mm clear of the wall, so they printed as loose towers and snapped off (2026-10-14).

The back cover's four screws sit 25.5 mm either side of the middle and 8 mm above and below it, each through a 10 mm lug joined to the cover's side wall, and the head's matching bosses are joined to its walls too. Further out and further up and down, the cover's curved back corners left only a thin curl of wall round each hole, which tore off with the supports (2026-10-18).
