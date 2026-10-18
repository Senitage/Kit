# The Pod

Kit's first robot body: a small 3D-printed desk Pod with a 1.5" screen for his
face, two hobby servos to turn and tilt his head, a pat sensor on top and an
ESP32 that runs it all over Wi-Fi. The brain stays on Kit's server; the Pod only
acts him out.

| Folder | What's in it |
|---|---|
| `firmware/kit_pod_face/` | The Pod's program (Arduino, ESP32): his face, the calm neck, pats, the link to Kit's brain, uploads over Wi-Fi, and a servo tuning page in the browser |
| `firmware/kit_pod_screen_test/`, `firmware/kit_pod_servo_test/` | Bench tests for the screen and the servos, before it's all boxed up |
| `cad/` | The printed parts, as code (CadQuery), with the print settings and assembly steps |
| `network/` | A Windows helper that lets the Pod reach Kit's server inside WSL |

How the Pod works, with pictures: `docs/2 How Kit Works/The Pod.md`, and in depth:
`docs/3 Deep Dives/Pod In Depth.md`. Building one: `docs/4 Guides/Building the Pod.md`.
