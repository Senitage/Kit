"""Step-by-step assembly pictures for Kit Pod v2, from the meshes kit_pod_v2.py writes to render/.

xvfb-run -a python3 render_steps.py
Writes assembly/step_NN.png and assembly/kit_pod_v2_assembly_guide.pdf.
"""

import math
import sys
from pathlib import Path

import vtk
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import cadquery as cq  # noqa: E402
import kit_pod_v2 as k  # noqa: E402
from render_pod import actor  # noqa: E402

R = HERE / "render"
OUT = HERE / "assembly"
FONT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
FONT_BODY = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"

SERVO = (0.15, 0.3, 0.85)
HORN = (0.97, 0.97, 0.97)
NEW = (1.0, 0.55, 0.1)       # arrows


def helper_meshes():
    """Horns and the servos' fitted-later positions, which the main export doesn't write."""
    horn_t = k.horn_single(0.0).rotate((0, 0, 0), (0, 1, 0), 90).translate((k.R_ARM_X0, k.TILT_Y, k.TILT_Z))
    horn_n = k.horn_double(0.0).translate((0, 0, k.DISC_Z0))
    for name, shape in {"horn_tilt": horn_t, "horn_turn": horn_n}.items():
        cq.exporters.export(shape, str(R / f"ref_{name}.stl"), tolerance=0.05)


def part(name, colour=None, move=(0, 0, 0), opacity=1.0):
    return {"name": name, "colour": colour or k.COLOURS.get(name, SERVO), "move": move, "opacity": opacity}


def mesh_path(name):
    return R / (f"{name}.stl" if (R / f"{name}.stl").exists() else f"ref_{name}.stl")


def arrow(start, end, colour=NEW, width=1.0):
    src = vtk.vtkArrowSource()
    src.SetTipLength(0.28)
    src.SetTipRadius(0.12 * width)
    src.SetShaftRadius(0.045 * width)
    sx, sy, sz = start
    d = [end[i] - start[i] for i in range(3)]
    length = math.sqrt(sum(v * v for v in d))
    t = vtk.vtkTransform()
    t.Translate(sx, sy, sz)
    x = [v / length for v in d]
    # rotate +X onto the direction
    axis = (0, -x[2], x[1])
    ang = math.degrees(math.acos(max(-1, min(1, x[0]))))
    if math.sqrt(axis[1] ** 2 + axis[2] ** 2) > 1e-6:
        t.RotateWXYZ(ang, *axis)
    elif x[0] < 0:
        t.RotateZ(180)
    t.Scale(length, length, length)
    m = vtk.vtkPolyDataMapper()
    m.SetInputConnection(src.GetOutputPort())
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.SetUserTransform(t)
    a.GetProperty().SetColor(*colour)
    a.GetProperty().SetAmbient(0.5)
    return a


def render(parts, arrows, view, focus, size=900):
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.96, 0.96, 0.95)
    ren.SetBackground2(0.86, 0.87, 0.88)
    ren.GradientBackgroundOn()
    for p in parts:
        a = actor(mesh_path(p["name"]), p["colour"], opacity=p["opacity"])
        t = vtk.vtkTransform()
        t.Translate(*p["move"])
        a.SetUserTransform(t)
        ren.AddActor(a)
    for s, e in arrows:
        ren.AddActor(arrow(s, e))
    for pos, inten in (((-150, -250, 300), 0.7), ((250, -100, 50), 0.35), ((0, 250, 150), 0.25)):
        light = vtk.vtkLight()
        light.SetPosition(*pos)
        light.SetFocalPoint(0, 0, 10)
        light.SetIntensity(inten)
        ren.AddLight(light)
    az, el, dist = view
    cam = ren.GetActiveCamera()
    cx, cy, cz = focus
    cam.SetFocalPoint(cx, cy, cz)
    cam.SetPosition(cx + dist * math.sin(math.radians(az)) * math.cos(math.radians(el)),
                    cy - dist * math.cos(math.radians(az)) * math.cos(math.radians(el)),
                    cz + dist * math.sin(math.radians(el)))
    cam.SetViewUp(0, 0, 1)
    cam.SetViewAngle(30)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetMultiSamples(8)
    win.AddRenderer(ren)
    win.SetSize(size, size)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.Update()
    png = vtk.vtkPNGWriter()
    tmp = OUT / "_tmp.png"
    png.SetFileName(str(tmp))
    png.SetInputConnection(w2i.GetOutputPort())
    png.Write()
    img = Image.open(tmp).convert("RGB")
    tmp.unlink()
    return img


def wrap(text, font, width):
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.getlength(trial) <= width:
            line = trial
        else:
            out.append(line)
            line = word
    return out + [line]


def caption(img, n, title, lines):
    w, h = img.size
    pad, line_h = 36, 34
    body = ImageFont.truetype(FONT_BODY, 25)
    rows = [r for text in lines for r in wrap(text, body, w - 2 * pad)]
    band = 40 + 54 + line_h * len(rows) + 24
    out = Image.new("RGB", (w, h + band), (255, 255, 255))
    out.paste(img, (0, band))
    d = ImageDraw.Draw(out)
    d.text((pad, 34), f"{n}. {title}", font=ImageFont.truetype(FONT, 38), fill=(25, 25, 30))
    for i, row in enumerate(rows):
        d.text((pad, 34 + 58 + i * line_h), row, font=body, fill=(70, 72, 78))
    return out


def steps():
    tz = k.TURN_TAB_Z
    ghost = 0.22
    yield ("Turn servo into the top plate", [
        "Shaft up, push it up through the grey plate.",
        "Two servo screws from underneath through its tabs.",
    ], [part("top"), part("turn_servo", SERVO, (0, 0, -22))],
        [((0, -20, tz - 40), (0, -20, tz - 22))], (-35, 22, 230), (0, 0, tz - 12))

    yield ("Body, plate and cap", [
        "Plate sits on the three pads inside the body; the cap goes on top.",
        "3 x M3 x 16 screws up from inside the body, through the plate, into the cap.",
    ], [part("body"), part("top", move=(0, 0, 14)), part("turn_servo", SERVO, (0, 0, 14)),
        part("cap", move=(0, 0, 32))],
        [((0, -40, 30), (0, -40, 14))], (-30, 18, 330), (0, 0, -15))

    yield ("Neck onto the turn servo", [
        "Press the cross horn into the pocket under the neck (a drop of glue holds it).",
        "Push the neck onto the servo shaft; horn screw down through the centre hole.",
    ], [part("body"), part("top"), part("cap"), part("turn_servo", SERVO),
        part("neck", move=(0, 0, 24)), part("horn_turn", HORN, (0, 0, 24))],
        [((30, 0, 30), (30, 0, 14))], (-30, 22, 300), (0, 0, 5))

    yield ("Single horn into the horn arm", [
        "One arm (on your right as Kit faces you) has a horn-shaped pocket on its inside face.",
        "Press the servo's single horn in, arm pointing down. A tiny drop of glue keeps it there.",
    ], [part("neck"), part("horn_tilt", HORN, (-10, 0, 0))],
        [((k.R_ARM_X0 - 22, -12, k.TILT_Z + 6), (k.R_ARM_X0 - 4, -12, k.TILT_Z + 6))],
        (-60, 25, 170), (5, 0, 15))

    yield ("Head on from the back", [
        "Hold the head behind the neck, level, and slide it forward (seen from behind here).",
        "The arms go in through the open ends of the slots in its floor; the pin on the left arm runs along the bracket's channel, then the head settles 2 mm onto it.",
    ], [part("body"), part("top"), part("cap"), part("neck"), part("horn_tilt", HORN),
        part("head", move=(0, 24, 0), opacity=0.45)],
        [((0, 50, k.TILT_Z + 16), (0, 28, k.TILT_Z + 16))], (155, 16, 300), (0, 12, 30))

    sx = -k.SLIDE + 0.2
    yield ("Tilt servo in through the back", [
        "Shaft toward the horn. Drop it in through the open back, pushed over toward the pin side,",
        "then lower it into the U-shaped wall and slide it across so its shaft goes into the horn.",
        "(Seen from the front here; the head is see-through.)",
    ], [part("neck"), part("horn_tilt", HORN), part("head", opacity=ghost),
        part("tilt_servo", SERVO, (sx, 22, 14), opacity=0.3), part("tilt_servo", SERVO, (sx, 0, 0))],
        [((sx - 2, 22, k.TILT_Z + 20), (sx - 2, 3, k.TILT_Z + 8)), ((-12, -8, k.TILT_Z + 12), (0, -8, k.TILT_Z + 12))],
        (-25, 28, 230), (0, 0, k.TILT_Z + 4))

    yield ("Fix the tilt servo", [
        "Two servo screws through its tabs into the wall, from the pin side, inside the head.",
        "Horn screw through the small hole below the ear on the horn side, into the shaft. Snug, not tight.",
    ], [part("neck"), part("horn_tilt", HORN), part("head", opacity=ghost), part("tilt_servo", SERVO)],
        [((50, 0, k.TILT_Z), (k.HW / 2 + 2, 0, k.TILT_Z))], (60, 15, 260), (5, 0, k.TILT_Z))

    yield ("Face and screen", [
        "Glue the face plate into the window from inside. Nothing shows from the front: no screw heads.",
        "Screen onto the four posts, header pins toward the horn-screw side, 4 x M2 x 4 screws from the back into the posts. (Pins option: a dab of hot glue on each pin.)",
    ], [part("head", opacity=0.35), part("face"), part("screen", (0.2, 0.4, 0.75), (0, 18, 0))],
        [((0, 32, k.FACE_ZC), (0, 6, k.FACE_ZC))], (150, 18, 260), (0, -15, k.FACE_ZC))

    yield ("Ears and back cover", [
        "Glue an orange ring into the groove on each side.",
        "Back cover on with 4 x M3 x 10 screws.",
    ], [part("head"), part("face"), part("ear", move=(0, 0, 0)), part("cover", move=(0, 22, 0)),
        part("neck"), part("cap"), part("top"), part("body")],
        [((0, 55, k.H_ZC + 18), (0, 33, k.H_ZC + 18))], (135, 18, 360), (0, 0, 20))

    yield ("ESP32, base and feet", [
        "Stand the ESP32 in the base's slots, USB toward the hole at the back left.",
        "Base on with 3 countersunk M3 x 8; glue the four feet in.",
    ], [part("body"), part("top"), part("cap"), part("neck"), part("head"), part("cover"), part("ear"),
        part("ESP32", (0.1, 0.45, 0.2), (0, 0, -30)), part("base", move=(0, 0, -30))],
        [((0, -45, k.LID_Z0 - 40), (0, -45, k.LID_Z0 - 15))], (-30, -12, 420), (0, 0, -20))


def main():
    OUT.mkdir(exist_ok=True)
    helper_meshes()
    pages = []
    for n, (title, lines, parts, arrows, view, focus) in enumerate(steps(), 1):
        img = caption(render(parts, arrows, view, focus), n, title, lines)
        img.save(OUT / f"step_{n:02d}.png")
        pages.append(img)
        print(f"step {n}: {title}")
    pages[0].save(OUT / "kit_pod_v2_assembly_guide.pdf", save_all=True, append_images=pages[1:], resolution=110)


if __name__ == "__main__":
    main()
