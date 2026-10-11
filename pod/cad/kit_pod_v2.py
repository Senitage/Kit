"""Kit Pod v2: a cute pill-head robot built around Dan's parts.

Run:  python3 kit_pod_v2.py   (needs `pip install cadquery`)
Writes kit_pod_v2_assembly.step (every part in place, plus the screen, servos and
ESP32 as reference bodies) and one STEP + STL per part, laid the way it prints.
`python3 kit_pod_v2.py check` reports any parts that hit each other, at rest and
with the head tilted fully up and down.

Frame: X to Kit's left (your right when you face him), Y toward his back, Z up.
The origin is on the turn axis, just under the neck.

How it moves: the turn servo hangs under the body's top plate and spins the neck
(a turntable with two arms). The tilt servo lives inside the head, low down; its
horn is held by the right arm and a pin on the left arm carries the other side, so
the head nods on the arms.

Parts (print colour in brackets):
  head      the pill head, front and sides               (white)
  cover     the back of the head                          (white)
  face      the black "glass" around the screen           (black)
  neck      turntable with the two arms                   (dark grey)
  cap       the domed top of the body, round the neck     (white)
  top       the plate between body and cap; holds the turn servo; its edge is a grey band (grey)
  body      the egg body                                  (white)
  base      bottom of the body; holds the ESP32           (grey)
  foot      x4, pressed or glued into the base            (dark grey)
  ear       x2, rings glued into the grooves on the head's sides (orange)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cadquery as cq

OUT = Path(__file__).parent

# ---------- measured by Dan ----------
board_w, board_h = 45.0, 37.0          # screen board, lying landscape, pins on the right (+X)
hole_dx, hole_dz = 39.6, 31.78         # its fixing holes, centre to centre
servo_l, servo_w, servo_h = 22.5, 12.0, 24.0

# ---------- measured by Dan (2026-10-10) ----------
glass_gap = 3.4 - 1.5     # screen glass front to the blue board: glass + board 3.4, board 1.5
# lit picture's gaps to the board edge, landscape with pins on the right, seen from the front
pic_left, pic_right, pic_top, pic_bottom = 8.6, 9.2, 1.7, 7.8
pic_dx = (pic_left - pic_right) / 2      # -0.3: picture centre a little left of the board centre
pic_dz = (pic_bottom - pic_top) / 2      # +3.05: picture centre above the board centre
spline_above_tab = 12.2   # top of the tabs to the top of the output shaft
tab_top_to_bottom = 20.0  # top of the tabs to the bottom of the servo (Dan, 2026-10-11)

# ---------- estimates ----------
win = 28.5                # window (the picture is 27.2 x 27.5)
shaft_from_end = 5.9
tab_len, tab_t = 32.2, 2.5
tab_under = tab_top_to_bottom - tab_t
tab_hole_from_centre = 13.9
horn_t = 1.6
esp_l, esp_w, esp_t = 52.0, 28.5, 1.6   # ESP32 dev board
pilot = 2.6               # M3 screw biting into plastic
clear3 = 3.4              # M3 clearance
servo_screw = 1.8

# ---------- layout ----------
EAR_OD, EAR_ID, EAR_PROUD = 20.0, 15.4, 1.4   # orange ear rings: sit 1 mm in the groove, stand 1.4 mm proud
TILT_DEG = 18.0                         # the firmware's TILT_RANGE
DISC_Z0 = 1.9                           # neck disc bottom = turn horn bottom
TURN_TAB_Z = DISC_Z0 + horn_t - spline_above_tab   # turn servo: top of its tabs, under the top plate
PLATE_T = 4.0
PLATE_Z1 = TURN_TAB_Z + PLATE_T         # top of the plate = bottom of the cap
LIP_R_IN, LIP_Z = 24.4, 4.5             # the cap's opening round the neck
TOP_SCREW_R = 28.4
DISC_R = 22.0
DISC_Z1 = DISC_Z0 + 4.5

# head
HW, HD, HH = 68.0, 52.0, 56.0
H_R, H_FRONT_R, H_BACK_R, H_WALL = 22.0, 10.0, 16.0, 2.2
H_Z0 = 14.0                             # head bottom
H_ZC = H_Z0 + HH / 2
FACE_ZC = H_ZC + 1.5                    # face window centre, a touch high so the screen board clears the head's corners
TILT_Z = H_Z0 + 10.0                    # tilt axis height (runs along X)
TILT_Y = 0.0                            # straight above the turn axis
H_Y0 = TILT_Y - 32.0                    # head front
H_Y1 = H_Y0 + HD
H_YC = (H_Y0 + H_Y1) / 2
H_CUT = H_Y1 - 9.0                      # head / cover split
FLOOR = H_Z0 + H_WALL
OPEN_W, OPEN_H, OPEN_R = 44.0, 32.0, 10.0
FLANGE_W, FLANGE_H, FLANGE_R, FLANGE_T = 47.6, 35.6, 11.8, 1.5
FACE_IN = H_Y0 + H_WALL                 # inside of the front wall
GLASS_Y = FACE_IN + FLANGE_T            # glass front
PCB_Y = GLASS_Y + glass_gap
BOARD_CX, BOARD_CZ = -pic_dx, FACE_ZC - pic_dz   # so the picture sits in the middle of the face

# tilt servo inside the head: shaft along +X, body toward the front (-Y), width along Z
ARM_T = 4.5
SLIDE = 4.5                             # room to slide the tilt servo off its horn (spline + hub), for fitting it
# top of the tilt servo's tabs, picked so the two arms sit the same distance either side of centre
TILT_TAB_X = ((tab_under + tab_t) + SLIDE + 3.0 + 0.5 - (spline_above_tab - horn_t)) / 2
SHAFT_TOP_X = TILT_TAB_X + spline_above_tab
R_ARM_X0 = SHAFT_TOP_X - horn_t                  # inside face of the right arm
L_BRACKET_X1 = TILT_TAB_X - (tab_under + tab_t) - SLIDE   # pin bracket inside the head; the servo's end slides up to it
L_BRACKET_X0 = L_BRACKET_X1 - 3.0
L_ARM_X1 = L_BRACKET_X0 - 0.5                    # inside face of the left arm
ARM_HALF_Y = 7.0
BULK_X0, BULK_X1 = TILT_TAB_X, TILT_TAB_X + 3.0  # tabs pull against the -X face of this wall
WIRE_XY = (-13.5, TILT_Y + 10.5)                 # wires from the head down through the neck

# body
B_Z0 = -56.0                            # bottom of the white shell
LID_Z0 = -62.0                          # bottom of the base
# outside of the body, cap included: (radius, height) from the lip down
OUTER_PTS = [(26.6, LIP_Z), (29.6, 2.0), (31.2, -2.0), (31.8, -6.0), (32.9, -14.0), (34.3, -26.0), (35.0, -38.0),
             (34.6, -48.0), (33.6, B_Z0)]
INNER_PTS = [(LIP_R_IN, LIP_Z + 1.0), (LIP_R_IN, LIP_Z - 1.6), (27.6, 0.0), (29.1, -3.0), (29.7, -7.0), (30.7, -14.0),
             (32.1, -26.0), (32.8, -38.0), (32.4, -48.0), (31.4, B_Z0 - 1)]
ESP_Y0 = 9.0                            # front (pin) face of the ESP32 board
ESP_Z0 = B_Z0                           # it stands on the base
ESP_CZ = ESP_Z0 + esp_w / 2
USB_X = -1                              # USB end of the board: -1 = the -X side


def box(x0, y0, z0, x1, y1, z1):
    return cq.Workplane().box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl(d, h, at, axis="Z"):
    """A cylinder of diameter d and length h starting at `at` along `axis`."""
    normal = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1), "-X": (-1, 0, 0), "-Y": (0, -1, 0), "-Z": (0, 0, -1)}[axis]
    xdir = (0, 1, 0) if "X" in axis else (1, 0, 0)
    return cq.Workplane(cq.Plane(origin=at, xDir=xdir, normal=normal)).circle(d / 2).extrude(h)


def cone(d0, d1, h, at, axis="Z"):
    normal = {"Z": (0, 0, 1), "-Z": (0, 0, -1), "Y": (0, 1, 0), "-Y": (0, -1, 0)}[axis]
    return (cq.Workplane(cq.Plane(origin=at, xDir=(1, 0, 0), normal=normal))
            .circle(d0 / 2).workplane(offset=h).circle(d1 / 2).loft())


def rrect_y(w, h, r, y0, y1, cx=0.0, cz=0.0):
    """A rounded rectangle in the XZ plane, extruded from y0 to y1."""
    pl = cq.Plane(origin=(cx, y0, cz), xDir=(1, 0, 0), normal=(0, 1, 0))
    return cq.Workplane(pl).sketch().rect(w, h).vertices().fillet(r).finalize().extrude(y1 - y0)


def rrect_z(w, d, r, z0, z1, cx=0.0, cy=0.0):
    pl = cq.Plane(origin=(cx, cy, z0), xDir=(1, 0, 0), normal=(0, 0, 1))
    return cq.Workplane(pl).sketch().rect(w, d).vertices().fillet(r).finalize().extrude(z1 - z0)


def rrect_x(d, h, r, x0, x1, cy=0.0, cz=0.0):
    pl = cq.Plane(origin=(x0, cy, cz), xDir=(0, 1, 0), normal=(1, 0, 0))
    return cq.Workplane(pl).sketch().rect(d, h).vertices().fillet(r).finalize().extrude(x1 - x0)


# ---------- SG90 and its horns, in the servo's own frame ----------
# Shaft along +z through the origin; z = 0 is the top of the mounting tabs;
# the body runs along +x from -shaft_from_end.
def sg90(clear=0.0):
    cx = servo_l / 2 - shaft_from_end
    bottom = -(tab_under + tab_t)
    body = box(-shaft_from_end - clear, -servo_w / 2 - clear, bottom - clear,
               servo_l - shaft_from_end + clear, servo_w / 2 + clear, bottom + servo_h + clear)
    tabs = box(cx - tab_len / 2 - clear, -servo_w / 2 - clear, -tab_t - clear, cx + tab_len / 2 + clear,
               servo_w / 2 + clear, 0)
    shaft = cyl(5 + 2 * clear, spline_above_tab - (servo_h + bottom), (0, 0, servo_h + bottom))
    return body.union(tabs).union(shaft)


def sg90_top_section(clear):
    """The part of the servo above its tabs (passes through a mounting wall)."""
    return box(-shaft_from_end - clear, -servo_w / 2 - clear, -tab_t, servo_l - shaft_from_end + clear,
               servo_w / 2 + clear, servo_h - tab_under - tab_t + clear)


def sg90_screw_holes(z0, z1, d=servo_screw):
    cx = servo_l / 2 - shaft_from_end
    out = None
    for s in (-1, 1):
        c = cyl(d, z1 - z0, (cx + s * tab_hole_from_centre, 0, z0))
        out = c if out is None else out.union(c)
    return out


def _arm(length, clear):
    r1, r2 = (7.5 + clear) / 2, (4.2 + clear) / 2
    t = horn_t + clear
    hub = cyl(2 * r1, t, (0, 0, 0))
    tip = cyl(2 * r2, t, (length, 0, 0))
    web = cq.Workplane().polyline([(0, -r1), (length, -r2), (length, r2), (0, r1)]).close().extrude(t)
    return hub.union(tip).union(web)


def horn_single(clear=0.3):
    return _arm(15.0, clear)


def horn_double(clear=0.3):
    return _arm(15.5, clear).union(_arm(15.5, clear).rotate((0, 0, 0), (0, 0, 1), 180))


def to_tilt(shape):
    """Servo frame -> world: shaft along +X, body toward the front (-Y), width along Z."""
    s = shape.rotate((0, 0, 0), (0, 0, 1), 180)      # body toward -x first
    return s.rotate((0, 0, 0), (1, 1, 1), 120).translate((TILT_TAB_X, TILT_Y, TILT_Z))


def to_turn(shape):
    """Servo frame -> world: shaft up on the turn axis, body toward +X, tabs under the top plate."""
    return shape.translate((0, 0, TURN_TAB_Z))


def tilted(shape, deg):
    return shape.rotate((0, TILT_Y, TILT_Z), (1, TILT_Y, TILT_Z), deg)


# ---------- head ----------
def head_solid(w, d, h, r, rf, rb, y0):
    s = cq.Workplane().box(w, d, h, centered=(True, False, True)).translate((0, y0, H_ZC))
    s = s.edges("|Y").fillet(r)
    s = s.faces("<Y").edges().fillet(rf)
    return s.faces(">Y").edges().fillet(rb)


def head_outer():
    return head_solid(HW, HD, HH, H_R, H_FRONT_R, H_BACK_R, H_Y0)


def head_shell():
    inner = head_solid(HW - 2 * H_WALL, HD - 2 * H_WALL, HH - 2 * H_WALL, H_R - H_WALL,
                       H_FRONT_R - H_WALL, H_BACK_R - H_WALL, H_Y0 + H_WALL)
    return head_outer().cut(inner)


def head_cover_bosses():
    return [(sx * 27.8, H_ZC + sz * 13.0) for sx in (-1, 1) for sz in (-1, 1)]


def arm_slot(x0, x1):
    """Slot in the head floor an arm passes through, long enough for the full tilt."""
    sweep = (TILT_Z - H_Z0) * math.tan(math.radians(TILT_DEG)) + 1.0
    return rrect_z(x1 - x0, 2 * (ARM_HALF_Y + sweep), 2.0, H_Z0 - 1, FLOOR + 5, (x0 + x1) / 2, TILT_Y)


def head():
    shell = head_shell().cut(box(-50, H_CUT, -10, 50, 60, 120))
    inside = head_outer()
    # face opening with a soft chamfer
    shell = shell.cut(rrect_y(OPEN_W, OPEN_H, OPEN_R, H_Y0 - 1, FACE_IN + 0.5, 0, FACE_ZC))
    shell = shell.cut(cq.Workplane(cq.Plane(origin=(0, H_Y0 - 0.01, FACE_ZC), xDir=(1, 0, 0), normal=(0, 1, 0)))
                      .sketch().rect(OPEN_W + 2, OPEN_H + 2).vertices().fillet(OPEN_R + 1).finalize()
                      .extrude(0.8, taper=45))
    # tilt servo mount: a wall its tabs pull against, open at the top so the servo drops in
    tab_front = TILT_Y - (servo_l / 2 - shaft_from_end) - tab_len / 2
    bulk = box(BULK_X0, tab_front - 0.5, FLOOR - 0.5, BULK_X1, H_CUT, TILT_Z + 8.0)
    bulk = bulk.cut(box(BULK_X0 - 1, TILT_Y - servo_l + shaft_from_end - 0.4, TILT_Z - servo_w / 2 - 0.4,
                        BULK_X1 + 1, TILT_Y + shaft_from_end + 0.4, 99))
    bulk = bulk.cut(to_tilt(sg90_screw_holes(-0.01, 3.0)))
    # bracket for the left arm's pin: a notch open at the bottom
    brk = box(L_BRACKET_X0, TILT_Y - ARM_HALF_Y, FLOOR - 0.5, L_BRACKET_X1, H_CUT, TILT_Z + 6.0)
    notch = box(L_BRACKET_X0 - 1, TILT_Y - 3.2, FLOOR - 1, L_BRACKET_X1 + 1, TILT_Y + 3.2, TILT_Z)
    brk = brk.cut(notch.union(cyl(6.4, 5, (L_BRACKET_X0 - 1, TILT_Y, TILT_Z), "X")))
    shell = shell.union(bulk.union(brk).intersect(inside))
    # bosses for the back cover
    for x, z in head_cover_bosses():
        shell = shell.union(cyl(7, 10, (x, H_CUT - 10, z), "Y").intersect(inside))
        shell = shell.cut(cyl(pilot, 9, (x, H_CUT - 9, z), "Y"))
    # floor: slots for the neck's arms and the wire hole
    shell = shell.cut(arm_slot(R_ARM_X0 - 0.5, R_ARM_X0 + ARM_T + 0.5))
    shell = shell.cut(arm_slot(L_ARM_X1 - ARM_T - 0.5, L_ARM_X1 + 0.3))
    shell = shell.cut(rrect_z(6.0, 9.0, 2.9, H_Z0 - 1, FLOOR + 1, *WIRE_XY))
    # hole in the right side for the tilt horn's screw
    shell = shell.cut(cyl(6.0, 12, (HW / 2 - 8, TILT_Y, TILT_Z), "X"))
    # thinner top over the pat sensor (copper tape goes inside here)
    shell = shell.cut(rrect_z(34, 24, 6, H_Z0 + HH - H_WALL - 0.01, H_Z0 + HH - 1.2, 0, H_YC))
    # grooves for the orange ear rings
    for sx in (-1, 1):
        ax = "-X" if sx > 0 else "X"
        at = (sx * (HW / 2 + 2), H_YC, H_ZC)
        shell = shell.cut(cyl(EAR_OD + 0.4, 3.0, at, ax).cut(cyl(EAR_ID - 0.4, 3.0, at, ax)))
    return shell


def ear(sx=1):
    """An orange ring glued into the groove on each side of the head."""
    ax = "-X" if sx > 0 else "X"
    at = (sx * (HW / 2 + EAR_PROUD), H_YC, H_ZC)
    r = cyl(EAR_OD, EAR_PROUD + 1.0, at, ax).cut(cyl(EAR_ID, EAR_PROUD + 1.0, at, ax))
    return r.edges(f"{'>' if sx > 0 else '<'}X").fillet(0.6)


def ears():
    return ear(1).union(ear(-1))


def cover():
    c = head_shell().intersect(box(-50, H_CUT, -10, 50, 60, 120))
    for x, z in head_cover_bosses():
        c = c.cut(cyl(clear3, 30, (x, H_CUT - 1, z), "Y"))
        c = c.cut(cyl(6.2, 30, (x, H_CUT + 3.0, z), "Y"))      # counterbore: screw heads sit inside
    return c


POST_D = 4.4              # screen posts: slim enough to miss the screen glass beside the holes
POST_TOP = PCB_Y - 0.15   # a hair short of the board, so the glass always sits flat on the face plate
BOARD_HOLE = 3.2          # the screen board's fixing holes (M3)


def screen_holes():
    return [(BOARD_CX + sx * hole_dx / 2, BOARD_CZ + sz * hole_dz / 2) for sx in (-1, 1) for sz in (-1, 1)]


def face_plate(style="studs"):
    """The black face round the screen. Two ways to hold the screen, to test-print:
    studs: M3 countersunk screws go in from the front of the face plate (before it's glued in) and stick out
           the back as studs; the screen goes on over them and an M3 nut holds each corner. Nuts come off
           from inside the head, so the screen can still come out after the face plate is glued in.
    pins:  plastic pins go through the screen's holes; a dab of hot glue on each pin holds it (peels off).
    """
    tab = rrect_y(OPEN_W - 0.3, OPEN_H - 0.3, OPEN_R - 0.15, H_Y0 + 0.4, FACE_IN, 0, FACE_ZC)
    flange = rrect_y(FLANGE_W, FLANGE_H, FLANGE_R, FACE_IN, GLASS_Y, 0, FACE_ZC)
    # the board sits low in the window (its picture is near its top edge), so the flange grows a pad under its holes
    pad = rrect_y(hole_dx + 6.0, hole_dz + 6.0, 4.0, FACE_IN, GLASS_Y, BOARD_CX, BOARD_CZ)
    p = tab.union(flange).union(pad)
    for x, z in screen_holes():
        p = p.union(cyl(POST_D, POST_TOP - GLASS_Y + 0.01, (x, GLASS_Y - 0.01, z), "Y"))
        if style == "pins":
            pin_len = PCB_Y + 1.5 + 1.6 - POST_TOP      # through the 1.5 mm board and 1.6 mm out the back
            pin = cyl(BOARD_HOLE - 0.4, pin_len, (x, POST_TOP - 0.01, z), "Y").faces(">Y").chamfer(0.4)
            p = p.union(pin)
    # window: square with a chamfer out to the front
    p = p.cut(rrect_y(win, win, 1.5, H_Y0, GLASS_Y + 0.1, 0, FACE_ZC))
    p = p.cut(cq.Workplane(cq.Plane(origin=(0, H_Y0 + 0.39, FACE_ZC), xDir=(1, 0, 0), normal=(0, 1, 0)))
              .sketch().rect(win + 2.4, win + 2.4).vertices().fillet(2.5).finalize().extrude(1.2, taper=45))
    room = head_solid(HW - 2 * H_WALL - 0.6, HD - 2 * H_WALL, HH - 2 * H_WALL - 0.6, H_R - H_WALL - 0.3,
                      H_FRONT_R - H_WALL + 0.3, H_BACK_R - H_WALL, FACE_IN - 0.02)
    p = p.intersect(room.union(box(-50, H_Y0 - 1, -10, 50, FACE_IN - 0.01, 120)))
    if style == "studs":
        for x, z in screen_holes():
            p = p.cut(cyl(3.4, 20, (x, H_Y0 - 5, z), "Y"))
            # countersink for the screw head, flush with the front of the flange (it sits against the head wall)
            p = p.cut(cone(6.6, 3.4, 1.6, (x, FACE_IN - 0.01, z), "Y"))
            p = p.cut(cyl(6.6, 3.0, (x, FACE_IN - 3.0, z), "Y"))      # head has to get past the tab too
    return p


# ---------- neck: turntable + the two arms ----------
def neck():
    disc = cyl(2 * DISC_R, DISC_Z1 - DISC_Z0, (0, 0, DISC_Z0)).edges(">Z").fillet(1.5)
    plane = cq.Plane(origin=(0, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))

    def arm(x0, x1):
        a = box(x0, TILT_Y - ARM_HALF_Y, DISC_Z1 - 0.5, x1, TILT_Y + ARM_HALF_Y, TILT_Z).edges("|Z").fillet(1.8)
        return a.union(cq.Workplane(plane).workplane(offset=x0).center(TILT_Y, TILT_Z)
                       .circle(ARM_HALF_Y).extrude(x1 - x0))

    n = disc.union(arm(R_ARM_X0, R_ARM_X0 + ARM_T)).union(arm(L_ARM_X1 - ARM_T, L_ARM_X1))
    # pin on the left arm
    n = n.union(cyl(5.9, L_BRACKET_X1 - 0.3 - L_ARM_X1, (L_ARM_X1 - 0.01, TILT_Y, TILT_Z), "X"))
    # tilt horn pocket on the inside of the right arm, arm pointing down, and a hole for its screw
    pocket = horn_single().rotate((0, 0, 0), (0, 1, 0), 90)     # thickness along +X, arm down
    n = n.cut(pocket.translate((R_ARM_X0 - 0.01, TILT_Y, TILT_Z)))
    n = n.cut(cyl(5.5, 10, (R_ARM_X0 - 1, TILT_Y, TILT_Z), "X"))
    # turn horn pocket underneath, its screw from above, and the wire hole
    n = n.cut(horn_double().translate((0, 0, DISC_Z0 - 0.01)))
    n = n.cut(cyl(5.5, 20, (0, 0, DISC_Z0 - 1)))
    n = n.cut(rrect_z(5.0, 9.0, 2.45, DISC_Z0 - 1, DISC_Z1 + 1, *WIRE_XY))
    return n


# ---------- body ----------
def revolve(pts, straight=0):
    """Solid of revolution about Z from a list of (r, z) points down one side. The
    first `straight` segments are straight lines, the rest a smooth curve."""
    wp = cq.Workplane("XZ").moveTo(0, pts[0][1]).lineTo(*pts[0])
    for pt in pts[1:straight + 1]:
        wp = wp.lineTo(*pt)
    wp = wp.spline(pts[straight + 1:], includeCurrent=True)
    wp = wp.lineTo(0, pts[-1][1]).close()
    return wp.revolve(360, (0, 0, 0), (0, 1, 0))


def top_screws():
    return [(TOP_SCREW_R * math.cos(math.radians(a)), TOP_SCREW_R * math.sin(math.radians(a))) for a in (90, 210, 330)]


def base_screws():
    return [(0.0, -28.0), (-25.5, -11.0), (25.5, -11.0)]


def esp_x(end):
    return USB_X * esp_l / 2 if end == "usb" else -USB_X * esp_l / 2


def shell():
    """The whole white egg, cap included, before it is cut into body and cap."""
    outer = revolve(OUTER_PTS)
    inner = revolve(INNER_PTS, straight=1)
    return outer, inner


def body():
    outer, inner = shell()
    outer = outer.intersect(box(-50, -50, B_Z0, 50, 50, TURN_TAB_Z))
    b = outer.cut(inner)
    # pads under the top plate: screws come up through them, the plate and into the cap
    for x, y in top_screws():
        pad = cyl(6.5, 8, (x, y, TURN_TAB_Z - 8)).union(cone(6.5, 0.4, 3.2, (x, y, TURN_TAB_Z - 8), "-Z"))
        b = b.union(pad.intersect(outer))
        b = b.cut(cyl(clear3, 20, (x, y, TURN_TAB_Z - 15)))
        b = b.cut(cyl(6.2, 10, (x, y, TURN_TAB_Z - 20)))     # room for the screw head under the pad
    # bosses for the base screws
    for x, y in base_screws():
        boss = cyl(7, 10, (x, y, B_Z0)).union(cone(7, 0.4, 3.5, (x, y, B_Z0 + 10)))
        b = b.union(boss.intersect(outer))
        b = b.cut(cyl(pilot, 8, (x, y, B_Z0 - 0.01)))
    # USB hole by the ESP32's USB end
    usb_y = ESP_Y0 + esp_t + 1.6
    ux = esp_x("usb")
    lo, hi = sorted((ux - 0.5 * USB_X, ux + 15 * USB_X))
    b = b.cut(rrect_x(8.6, 13.0, 4.29, lo, hi, usb_y, ESP_CZ))
    # pinholes over BOOT and EN, with guide tubes so a paper clip finds the buttons
    bx = ux - USB_X * 3.5
    for dz in (-8.5, 8.5):
        tube = cyl(5.5, 20, (bx, ESP_Y0 + esp_t + 3.0, ESP_CZ + dz), "Y")
        b = b.union(tube.intersect(outer))
        b = b.cut(cyl(2.4, 40, (bx, ESP_Y0, ESP_CZ + dz), "Y"))
    # front light slot (a shallow groove)
    # (cut as a box and two round ends: a one-piece rounded cutter fails against the curved body)
    b = b.cut(box(-3.0, -40.0, -36.0, 3.0, -33.4, -20.0))
    for z in (-36.0, -20.0):
        b = b.cut(cyl(6.0, 6.6, (0, -40.0, z), "Y"))
    # speaker grille on the +X side
    gz, gr = -28.0, 9.5
    for i in range(-3, 4):
        for j in range(-3, 4):
            y = (i + (j % 2) * 0.5) * 3.6
            z = gz + j * 3.1
            if (y * y + (z - gz) ** 2) <= gr * gr:
                b = b.cut(cyl(2.0, 14, (28.0, y, z), "X"))
    return b


def cap():
    outer, inner = shell()
    outer = outer.intersect(box(-50, -50, PLATE_Z1, 50, 50, 20))
    c = outer.cut(inner)
    for x, y in top_screws():
        c = c.union(cyl(5.6, 6, (x, y, PLATE_Z1)).intersect(outer))
        c = c.cut(cyl(pilot, 5, (x, y, PLATE_Z1 - 0.01)))
    return c


def top_plate():
    outer, _ = shell()
    p = outer.intersect(box(-50, -50, TURN_TAB_Z, 50, 50, PLATE_Z1))
    p = p.cut(to_turn(sg90_top_section(0.4)))
    p = p.cut(to_turn(sg90_screw_holes(0.0, PLATE_T - 0.6)))
    for x, y in top_screws():
        p = p.cut(cyl(clear3, 20, (x, y, TURN_TAB_Z - 1)))
    # wire slot: an arc so the neck can turn with the wires through it
    a_mid = math.degrees(math.atan2(WIRE_XY[1], WIRE_XY[0]))
    r = math.hypot(*WIRE_XY)
    slot = None
    for a in range(int(a_mid - 43), int(a_mid + 44), 3):
        x, y = r * math.cos(math.radians(a)), r * math.sin(math.radians(a))
        c = cyl(4.6, 10, (x, y, TURN_TAB_Z - 1))
        slot = c if slot is None else slot.union(c)
    return p.cut(slot)


def feet():
    return [(19 * math.cos(math.radians(a)), 19 * math.sin(math.radians(a))) for a in (45, 135, 225, 315)]


def base():
    pts = [(0, B_Z0), (33.5, B_Z0), (33.5, B_Z0 - 0.6), (28.1, LID_Z0), (0, LID_Z0)]
    b = cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))
    # ESP32 holders: a slot for each end of the board
    for end in (-1, 1):
        xe = end * esp_l / 2
        post = box(min(xe - end * 2.6, xe + end * 1.6), ESP_Y0 - 2.5, B_Z0 - 0.01,
                   max(xe - end * 2.6, xe + end * 1.6), ESP_Y0 + esp_t + 2.5, B_Z0 + 5.0)
        slot = box(min(xe - end * 4, xe + end * 0.4), ESP_Y0 - 0.15, B_Z0, max(xe - end * 4, xe + end * 0.4),
                   ESP_Y0 + esp_t + 0.15, B_Z0 + 6)
        b = b.union(post).cut(slot)
    for x, y in base_screws():
        b = b.cut(cyl(clear3, 10, (x, y, LID_Z0 - 1)))
        b = b.cut(cone(6.2, 3.4, 1.4, (x, y, LID_Z0 - 0.01)))
    for x, y in feet():
        b = b.cut(cyl(8.4, 1.6, (x, y, LID_Z0 - 0.01)))
    return b


def foot(at=(0.0, 0.0)):
    f = cyl(12, 2.5, (at[0], at[1], LID_Z0 - 2.5)).edges("<Z").fillet(1.2)
    return f.union(cyl(8.0, 1.5, (at[0], at[1], LID_Z0 - 0.01)))


# ---------- reference parts ----------
def screen():
    pcb = box(BOARD_CX - board_w / 2, PCB_Y, BOARD_CZ - board_h / 2, BOARD_CX + board_w / 2, PCB_Y + 1.5,
              BOARD_CZ + board_h / 2)
    for x, z in screen_holes():
        pcb = pcb.cut(cyl(BOARD_HOLE, 5, (x, PCB_Y - 1, z), "Y"))
    # glass: about 33.6 wide round the picture, from the board's top edge down past the picture (ribbon end)
    glass = box(-16.8, GLASS_Y, FACE_ZC - 13.75 - 5.0, 16.8, PCB_Y, BOARD_CZ + board_h / 2)
    header = box(BOARD_CX + board_w / 2 - 3.5, PCB_Y + 1.5, BOARD_CZ - 9, BOARD_CX + board_w / 2 - 1,
                 PCB_Y + 1.5 + 14, BOARD_CZ + 9)       # pins with the jumper plugs on them
    return pcb.union(glass).union(header)


def esp32():
    x0, x1 = -esp_l / 2, esp_l / 2
    pcb = box(x0, ESP_Y0, ESP_Z0, x1, ESP_Y0 + esp_t, ESP_Z0 + esp_w)
    mx = esp_x("other")
    module = box(min(mx, mx + USB_X * 25.5), ESP_Y0 + esp_t, ESP_CZ - 9, max(mx, mx + USB_X * 25.5),
                 ESP_Y0 + esp_t + 3.2, ESP_CZ + 9)
    ux = esp_x("usb")
    usb = box(min(ux, ux - USB_X * 5.5), ESP_Y0 + esp_t, ESP_CZ - 4, max(ux, ux - USB_X * 5.5),
              ESP_Y0 + esp_t + 3.0, ESP_CZ + 4)
    rows = None
    for zr in (ESP_Z0 + 2.5, ESP_Z0 + esp_w - 2.5):   # header pins with jumper plugs, on the front
        r = box(-19, ESP_Y0 - 22, zr - 1.3, 19, ESP_Y0, zr + 1.3)
        rows = r if rows is None else rows.union(r)
    return pcb.union(module).union(usb).union(rows)


def parts():
    return {"head": head(), "cover": cover(), "face": face_plate(), "neck": neck(), "cap": cap(),
            "top": top_plate(), "body": body(), "base": base(), "ear": ears()}


COLOURS = {
    "head": (0.95, 0.94, 0.91), "cover": (0.95, 0.94, 0.91), "face": (0.04, 0.04, 0.05),
    "neck": (0.33, 0.34, 0.37), "cap": (0.95, 0.94, 0.91), "top": (0.60, 0.61, 0.63), "body": (0.95, 0.94, 0.91),
    "base": (0.60, 0.61, 0.63), "foot": (0.40, 0.41, 0.43), "ear": (0.96, 0.52, 0.16),
}
TILTING = {"head", "cover", "face", "ear", "screen", "tilt servo"}


def references():
    return {
        "screen": (screen(), (0.2, 0.4, 0.75)), "tilt servo": (to_tilt(sg90()), (0.15, 0.3, 0.85)),
        "turn servo": (to_turn(sg90()), (0.15, 0.3, 0.85)), "ESP32": (esp32(), (0.1, 0.45, 0.2)),
    }


def check(p):
    """Every pair of solids that overlaps, at rest and with the head tilted fully up and down."""
    solids = {**p, **{k: v[0] for k, v in references().items()}}
    for i, at in enumerate(feet()):
        solids[f"foot {i + 1}"] = foot(at)
    problems = []
    for deg in (0, TILT_DEG, -TILT_DEG):
        moved = {k: tilted(v, deg) if k in TILTING else v for k, v in solids.items()}
        names = list(moved)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ba, bb = moved[a].val().BoundingBox(), moved[b].val().BoundingBox()
                if (ba.xmax < bb.xmin or bb.xmax < ba.xmin or ba.ymax < bb.ymin or bb.ymax < ba.ymin
                        or ba.zmax < bb.zmin or bb.zmax < ba.zmin):
                    continue
                vol = moved[a].intersect(moved[b]).val().Volume()
                if vol > 0.05:
                    problems.append((deg, a, b, round(vol, 2)))
    return problems


def main():
    p = parts()
    asm = cq.Assembly(name="kit_pod_v2")
    for name, shape in p.items():
        asm.add(shape, name=name, color=cq.Color(*COLOURS[name]))
    for i, at in enumerate(feet()):
        asm.add(foot(at), name=f"foot {i + 1}", color=cq.Color(*COLOURS["foot"]))
    for name, (shape, col) in references().items():
        asm.add(shape, name=f"{name} (reference)", color=cq.Color(*col))
    asm.save(str(OUT / "kit_pod_v2_assembly.step"))

    # whole parts in place, for the preview renders
    (OUT / "render").mkdir(exist_ok=True)
    for name, shape in {**p, "foot": foot()}.items():
        cq.exporters.export(shape, str(OUT / "render" / f"{name}.stl"), tolerance=0.03, angularTolerance=0.15)
    for name, (shape, _) in references().items():
        cq.exporters.export(shape, str(OUT / "render" / f"ref_{name.replace(' ', '_')}.stl"), tolerance=0.05)

    # each part laid the way it prints
    flat = {
        "head": p["head"].rotate((0, 0, 0), (1, 0, 0), -90),      # back opening down
        "cover": p["cover"].rotate((0, 0, 0), (1, 0, 0), 90),     # cut face down
        "face": p["face"].rotate((0, 0, 0), (1, 0, 0), 90),       # front down (the "studs" way)
        "face_pins": face_plate("pins").rotate((0, 0, 0), (1, 0, 0), 90),
        "neck": p["neck"],                                        # turntable down
        "cap": p["cap"],                                          # upright, bottom down
        "top": p["top"],
        "body": p["body"],                                        # upright, open bottom down
        "base": p["base"],
        "foot": foot(),
        "ear": ear(1).rotate((0, 0, 0), (0, 1, 0), -90),           # flat face down; print two
    }
    for name, shape in flat.items():
        bb = shape.val().BoundingBox()
        shape = shape.translate((-bb.center.x, -bb.center.y, -bb.zmin))
        cq.exporters.export(shape, str(OUT / f"kit_pod_v2_{name}.step"))
        cq.exporters.export(shape, str(OUT / f"kit_pod_v2_{name}.stl"), tolerance=0.02, angularTolerance=0.1)
        bb = shape.val().BoundingBox()
        print(f"{name:6s} {bb.xlen:5.1f} x {bb.ylen:5.1f} x {bb.zlen:5.1f}  "
              f"{'valid' if shape.val().isValid() else 'INVALID'}")


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        found = check(parts())
        print("\n".join(f"tilt {d:+5.1f}: {a} hits {b} ({v} mm3)" for d, a, b, v in found) or "No parts hit each other.")
    else:
        main()
