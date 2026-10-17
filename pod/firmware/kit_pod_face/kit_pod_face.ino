// Kit Pod: Kit's 2D face (the "Kit 2D" character) on the 1.5" OLED, with the
// turn and tilt servos, the pat sensor and uploads over Wi-Fi.
//
// A port of Kit's desk face (kit/desk/glow.py and kit/face/rig.py) using the
// "kit2d_screen" look from the character sheet kit2d.json: glowing eyes with lids,
// brows, mouth, blush, 20 moods with their own glow colours, and 19 gestures.
// kit2d_sheet.h is made from the sheet by make_sheet.py, so the Pod and the desk
// share the same numbers.
//
// Linked to Kit's brain over Wi-Fi (copy kit_server.example.h to kit_server.h and fill it in): his resting face follows
// Kit's mood and feelings, a reply's emotion shows while he answers, his mouth moves
// while he talks, he sleeps when Kit sleeps, and a pat reaches Kit. Without the link
// (or while Kit's server is down) he idles on his own: looks around, blinks, changes
// mood now and then, and dozes off when nobody's around. Pat him to wake him.
//
// The calm neck: the face is lively but the neck is not. The eyes dart about on the
// screen; the head only moves when Kit pays attention to something: a glance round the
// room now and then (more often when he's lively, rarely when he's sleepy or focused),
// something catching his eye ("look"), a real gesture, or his mood's posture (a droop
// when sad, head down asleep). Small looks are left to the eyes, every head move is
// slow and eased, and the head stays put a few seconds after each move.
// Serial Monitor commands (115200 baud):
//   a mood:     neutral happy curious thinking surprised concerned playful tired proud
//               excited sad confused shy grumpy focused relieved fond scared sleepy dreaming
//   a gesture:  nod shake tilt_head perk_up droop look_away shrug wave bounce lean_in
//               wink laugh sigh startle yawn double_take wiggle peek look_up
//   a state:    sleep, wake, listen, think, talk, offline, awake
//   attention:  look (catch his eye somewhere), look -0.8 (left .. right, -1..1),
//               look 0.5 -0.3 (and down .. up), glance (look round the room now)
//   other:      tour (go through every mood), still (servos off), help
//
// Servo tuning page: once he's on Wi-Fi, open http://kit-pod.local (or the address the
// Serial Monitor prints) in a browser on the PC or a phone. It drives the turn and tilt
// servos by hand, holds them at 90 degrees while you fit the horns, and sets each
// servo's centre, range and direction. Those are saved in the Pod's own memory, so
// they survive restarts and new uploads. Close the page and Kit has his neck back.
//
// Board: ESP32 Dev Module. Libraries: "Adafruit SSD1351 library", "Adafruit GFX Library",
// "ESP32Servo". Wi-Fi uploads use ArduinoOTA, which comes with the ESP32 boards.
// Wiring: screen VCC 3V3, GND GND, DIN D23, CLK D18, CS D5, DC RX2 (16), RST TX2 (17).
//         turn servo orange D13, tilt servo orange D14, servo red VIN, servo brown GND, pat wire D32.
//
// Uploading:
//   First time: by USB as before (hold BOOT, servo red wires unplugged). Copy
//   wifi_settings.example.h to wifi_settings.h and fill it in first.
//   After that: Tools > Port > "kit-pod at 192.168..." and press Upload. No cable or
//   buttons. The face shows a bar while it loads, then Kit restarts.

#include <SPI.h>
#include <math.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1351.h>
#include <ESP32Servo.h>
#include <WebServer.h>
#include <Preferences.h>
#include "wifi_settings.h"
#include "kit_server.h"
#include "kit2d_sheet.h"
#include "tuning_page.h"

// ---------- pins and servo setup ----------
const int PIN_CS = 5, PIN_DC = 16, PIN_RST = 17, PIN_SCK = 18, PIN_MOSI = 23;
const int PIN_TURN = 13, PIN_TILT = 14, PIN_TOUCH = 32;
// Where the neck sits. These are the starting values: the servo tuning page (see the top of
// the file) sets your own and saves them in the Pod's memory, and they're loaded at start-up.
const float DEFAULT_TURN_CENTRE = 90, DEFAULT_TURN_RANGE = 35;  // degrees
const float DEFAULT_TILT_CENTRE = 90, DEFAULT_TILT_RANGE = 18;  // 18 is as far as the printed head can nod
float TURN_CENTRE = DEFAULT_TURN_CENTRE, TURN_RANGE = DEFAULT_TURN_RANGE;
float TILT_CENTRE = DEFAULT_TILT_CENTRE, TILT_RANGE = DEFAULT_TILT_RANGE;
float TURN_SIGN = 1;                             // -1 if Kit turns the wrong way
float TILT_SIGN = 1;                             // -1 if Kit looks up when he should look down
const unsigned long TUNE_LETGO_MS = 15000;       // the tuning page hands the neck back this long after it goes quiet
const float TUNE_SPEED = 60;                     // degrees a second when the tuning page moves a servo

// The calm neck (see the top of the file). Tune these to taste.
const float NECK_DEADBAND_TURN = 9;              // degrees; smaller turns are left to the eyes
const float NECK_DEADBAND_TILT = 4;              // degrees; same for tilt
const unsigned long NECK_HOLD_MS = 3000;         // the head stays put at least this long after a move
const float NECK_SPEED_CALM = 30;                // degrees a second when he's low on energy
const float NECK_SPEED_LIVELY = 80;              // degrees a second when he's lively
const float NECK_SPEED_NOTICE = 120;             // degrees a second when something catches his eye
const float GLANCE_EVERY_CALM_S = 300;           // about how often he glances round when calm
const float GLANCE_EVERY_LIVELY_S = 50;          // and when lively (neutral is in between, ~2.5 min)
const float NECK_GESTURE_SIZE = 0.7;             // gestures on the neck compared with the old size

const int W = 128, H = 128;
const float FACE_ZOOM = 1.15;     // the Pod's screen is small, so Kit's face is drawn a bit bigger than the sheet
const float S = 128 * FACE_ZOOM;  // face size in pixels (kit2d_screen fills the screen at 1.0)
const float OX = (W - S) / 2, OY = (H - S) / 2;  // where the face's corner sits on the screen
const unsigned long DOZE_AFTER_MS = 3UL * 60 * 1000;  // falls asleep after 3 minutes alone

// ---------- state ----------
// (These types sit above every function so the Arduino app can build the sketch.)
// One frame of the face: what the desk calls a FaceFrame.
struct Frame {
  float openL, openR, squint, tilt, size, lookX, lookY, blush, glow, talk;
  float dx, dy, rot, sx, sy, scale;
  float mouth, mouthOpen, mouthO, brow, browUp;
  float r, g, b;  // glow colour
};

// A small polyline for brows and mouths, in face pixels.
struct Poly { int n; float x[40], y[40]; float x0, y0, x1, y1; };

Adafruit_SSD1351 oled(W, H, &SPI, PIN_CS, PIN_DC, PIN_RST);
GFXcanvas16 canvas(W, H);
Servo turnServo, tiltServo;

Pose cur = POSE_DEFAULT;
int emotion = 0;                 // index into MOODS
const char *state = "awake";     // awake, sleeping, offline, thinking, listening, speaking
float glowLevel = 1;
float colour[3] = {(float)MOODS[0].colour[0], (float)MOODS[0].colour[1], (float)MOODS[0].colour[2]};
bool tour = false, servosEnabled = true, otaReady = false, updating = false;
int tourIndex = 0;
unsigned long nextTour = 0, nextIdle = 0, lastActive = 0, lastPat = 0;
int patCount = 0;
float dartX = 0, dartY = 0;
unsigned long nextDart = 0;
unsigned long blinkStart = 0, nextBlink = 2000;
bool doubleBlink = false;
float breathPhase = 0;
int touchBaseline = 0;

int gesture = -1;
unsigned long gestureStart = 0;

float turnPos = TURN_CENTRE, tiltPos = TILT_CENTRE;  // what the servos were last told
unsigned long servoStill = 0;
bool servosOn = false;

// The calm neck. "Aim" is where his attention is, in the face's look units
// (x -1 left .. 1 right, y -1 up .. 1 down); 0, 0 is straight ahead.
bool gestureMovesNeck = false;    // only real gestures move the neck; idle fidgets are face-only
float gestureDX = 0, gestureDY = 0;
float aimX = 0, aimY = 0;
unsigned long aimUntil = 0;       // when the attention ends and he drifts back (0 = it doesn't)
unsigned long aimHoldMs = 0;      // how long to hold once he arrives
bool aimNotice = false;           // a quick "what's that?" rather than a lazy glance
unsigned long lastAttention = 0;  // when he last stopped paying attention to something
float headTurn = TURN_CENTRE, headTilt = TILT_CENTRE;  // the head's resting place, without gestures
bool neckMoving = false;
float moveFromT, moveFromL, moveToT, moveToL, moveSecs;
unsigned long moveStart = 0, neckHoldUntil = 0;

// The servo tuning page. While it has the neck, Kit's own neck moves stop and the
// servos go where the page says, in raw servo degrees (0..180).
WebServer web(80);
Preferences prefs;
bool webReady = false, tuning = false, tuneFree = false;
float tuneTurn = 90, tuneTilt = 90;
unsigned long tuneUntil = 0;

// ---------- helpers ----------
float lerpf(float a, float b, float t) { return a + (b - a) * t; }
float clamp01(float x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }
float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
float frand(float lo, float hi) { return lo + (hi - lo) * (random(0, 10001) / 10000.0f); }
float *poseField(Pose &p, int i) { return &p.open + i; }
const int N_POSE = sizeof(Pose) / sizeof(float);

int findMood(const char *name) {
  for (int i = 0; i < N_MOODS; i++) if (!strcmp(name, MOODS[i].name)) return i;
  return -1;
}

const StateRule *stateRule() {
  for (int i = 0; i < N_STATES; i++) if (!strcmp(state, STATES[i].name)) return &STATES[i];
  return nullptr;
}

// The emotion's pose as the state bends it (character.py state_pose).
Pose statePose() {
  Pose p = MOODS[emotion].pose;
  const StateRule *r = stateRule();
  if (!r) return p;
  if (r->pose && (!r->only_from || !strcmp(MOODS[emotion].name, r->only_from))) {
    int m = findMood(r->pose);
    if (m >= 0) p = MOODS[m].pose;
  }
  for (int i = 0; i < N_POSE; i++) {
    *poseField(p, i) += r->add[i];
    if (r->has_set[i]) *poseField(p, i) = r->set[i];
  }
  return p;
}

// The glow colour: the colour of the mood on show (the state's pose if it has one).
const uint8_t *targetColour() {
  if (!strcmp(state, "offline")) return COLOUR_EYE_OFFLINE;
  const StateRule *r = stateRule();
  if (r && r->pose && (!r->only_from || !strcmp(MOODS[emotion].name, r->only_from))) {
    int m = findMood(r->pose);
    if (m >= 0) return MOODS[m].colour;
  }
  return MOODS[emotion].colour;
}

void setMood(int i) {
  emotion = i;
  Serial.printf("Mood: %s\n", MOODS[i].name);
}

bool setMood(const char *name) {
  int i = findMood(name);
  if (i < 0) return false;
  setMood(i);
  return true;
}

// moveNeck: a real gesture (a command, a pat, waking up) moves the head too;
// idle fidgets pass false so they stay on the face and the servos stay quiet.
bool play(const char *name, bool moveNeck) {
  for (int i = 0; i < N_GESTURES; i++) {
    if (!strcmp(name, GESTURES[i].name)) {
      gesture = i; gestureStart = millis(); gestureMovesNeck = moveNeck;
      Serial.printf("Gesture: %s\n", name);
      return true;
    }
  }
  return false;
}

bool play(const char *name) { return play(name, true); }

// ---------- gestures (character.py move_at) ----------
float easeInOut(float t) { return t < 0.5f ? 2 * t * t : 1 - powf(-2 * t + 2, 2) / 2; }

float shapeAt(float t, const Shape &s) {
  switch (s.type) {
    case SH_BUMP: {
      float v = (t < s.a || t > s.b) ? 0 : sinf(PI * (t - s.a) / (s.b - s.a));
      return s.c > 0 ? fminf(1, v * s.c) : v;
    }
    case SH_HOLD:
      if (t < s.a) return easeInOut(t / s.a);
      if (t > s.b) return 1 - easeInOut((t - s.b) / (1 - s.b));
      return 1;
    case SH_SIN: return sinf(PI * s.a * t);
    case SH_ABS_SIN: return fabsf(sinf(PI * s.a * t));
    case SH_LINE: return s.a + s.b * t;
    case SH_JOLT: return t < s.a ? t / s.a : 1 - easeInOut((t - s.a) / (1 - s.a));
    default: return 1;
  }
}

// Fills ch[] with the gesture's offsets now (sx, sy and scale start at 1).
void gestureOffsets(unsigned long now, float ch[N_CHANNELS]) {
  for (int i = 0; i < N_CHANNELS; i++) ch[i] = 0;
  ch[CH_SX] = ch[CH_SY] = ch[CH_SCALE] = 1;
  if (gesture < 0) return;
  const Gesture &g = GESTURES[gesture];
  float t = (now - gestureStart) / 1000.0f / g.seconds;
  if (t >= 1) { gesture = -1; return; }
  for (int i = g.first; i < g.first + g.count; i++) {
    float v = TERMS[i].amount;
    for (int k = 0; k < 3 && TERMS[i].shapes[k].type != SH_NONE; k++) v *= shapeAt(t, TERMS[i].shapes[k]);
    ch[TERMS[i].channel] += v;
  }
}

// ---------- one frame of the face ----------

void polyBox(Poly &p, float pad) {
  p.x0 = p.y0 = 1e9; p.x1 = p.y1 = -1e9;
  for (int i = 0; i < p.n; i++) {
    p.x0 = fminf(p.x0, p.x[i]); p.x1 = fmaxf(p.x1, p.x[i]);
    p.y0 = fminf(p.y0, p.y[i]); p.y1 = fmaxf(p.y1, p.y[i]);
  }
  p.x0 -= pad; p.y0 -= pad; p.x1 += pad; p.y1 += pad;
}

void quadTo(Poly &p, float x0, float y0, float cx, float cy, float x1, float y1, int steps) {
  for (int i = (p.n ? 1 : 0); i <= steps; i++) {
    float t = (float)i / steps, u = 1 - t;
    p.x[p.n] = u * u * x0 + 2 * u * t * cx + t * t * x1;
    p.y[p.n] = u * u * y0 + 2 * u * t * cy + t * t * y1;
    p.n++;
  }
}

void cubicTo(Poly &p, float x0, float y0, float ax, float ay, float bx, float by, float x1, float y1, int steps) {
  for (int i = 1; i <= steps; i++) {
    float t = (float)i / steps, u = 1 - t;
    p.x[p.n] = u * u * u * x0 + 3 * u * u * t * ax + 3 * u * t * t * bx + t * t * t * x1;
    p.y[p.n] = u * u * u * y0 + 3 * u * u * t * ay + 3 * u * t * t * by + t * t * t * y1;
    p.n++;
  }
}

// Distance from a point to the polyline (closed adds the last-to-first edge).
float polyDist(const Poly &p, float px, float py, bool closed, bool *inside) {
  float best = 1e9;
  bool in = false;
  int edges = closed ? p.n : p.n - 1;
  for (int i = 0; i < edges; i++) {
    int j = (i + 1) % p.n;
    float ax = p.x[i], ay = p.y[i], bx = p.x[j], by = p.y[j];
    float ex = bx - ax, ey = by - ay, wx = px - ax, wy = py - ay;
    float l2 = ex * ex + ey * ey;
    float t = l2 > 0 ? clamp01((wx * ex + wy * ey) / l2) : 0;
    float dx = wx - ex * t, dy = wy - ey * t;
    best = fminf(best, dx * dx + dy * dy);
    if (closed && ((ay > py) != (by > py)) && (px < ax + (py - ay) * ex / ey)) in = !in;
  }
  if (inside) *inside = in;
  return sqrtf(best);
}

// Signed distance (pixels) to one eye: a rounded pill with the upper lid cut by
// tilt and the lower lid by squint (glow.py _eye_path).
float eyeDist(float px, float py, float cx, float cy, float w, float h, const Frame &f, int side) {
  h = fmaxf(h, S * 0.012f);
  float hw = w / 2, hh = h / 2;
  float r = fminf(S * EYES_CORNER, fminf(hw, hh));
  float qx = fabsf(px - cx) - hw + r, qy = fabsf(py - cy) - hh + r;
  float ox = fmaxf(qx, 0), oy = fmaxf(qy, 0);
  float d = sqrtf(ox * ox + oy * oy) + fminf(fmaxf(qx, qy), 0) - r;
  float hfull = fmaxf(h, S * 0.03f);
  if (fabsf(f.tilt) > 0.02f) {
    float slope = f.tilt * 0.55f * (side < 0 ? -1 : 1);
    float y0 = cy - hfull / 2 + hfull * 0.32f * fabsf(f.tilt);
    float lineY = y0 + slope * (px - cx);
    d = fmaxf(d, (lineY - py) / sqrtf(1 + slope * slope));
  }
  if (f.squint > 0.02f) {
    float R = w * EYES_SQUINT_ROUND;
    float ccy = cy + hfull / 2 + R - hfull * f.squint * EYES_SQUINT_LIFT;
    float dc = sqrtf((px - cx) * (px - cx) + (py - ccy) * (py - ccy)) - R;
    d = fmaxf(d, -dc);
  }
  return d;
}

// Brow: a thin arc above the eye (glow.py _paint_brow).
void makeBrow(Poly &p, float cx, float cy, const Frame &f, int side) {
  float y = cy - S * BROWS_ABOVE * fmaxf(1.0f, f.size) - f.browUp * S * BROWS_LIFT;
  float half = S * BROWS_WIDTH / 2, slant = f.brow * S * BROWS_SLANT;
  float inner = -side;
  p.n = 0;
  quadTo(p, cx - inner * half, y + slant * 0.4f, cx, y - S * BROWS_ARCH + slant * 0.2f,
         cx + inner * half, y - slant, 10);
  polyBox(p, S * BROWS_THICK);
}

// Mouth: "o", open "D", or a line bowed into a smile or frown (glow.py _paint_mouth).
// Returns 0 line, 1 open, 2 o.
int makeMouth(Poly &p, float mx, float my, const Frame &f, float &oRx, float &oRy) {
  float talk = f.talk * MOUTH_TALK;
  float w = S * MOUTH_WIDTH;
  p.n = 0;
  if (f.mouthO > 0.2f) {
    float r = S * MOUTH_ROUND * (0.45f + 0.55f * f.mouthO);
    oRx = r * 0.85f; oRy = r;
    p.x0 = mx - oRx - 2; p.x1 = mx + oRx + 2; p.y0 = my - oRy - 2; p.y1 = my + oRy + 2;
    return 2;
  }
  float opened = fmaxf(f.mouthOpen, talk);
  if (opened > 0.12f) {
    float d = S * MOUTH_OPEN * opened;
    w *= 0.8f + 0.4f * opened;
    quadTo(p, mx - w / 2, my - d * 0.25f, mx, my - d * 0.05f, mx + w / 2, my - d * 0.25f, 10);
    cubicTo(p, mx + w / 2, my - d * 0.25f, mx + w / 2, my + d * 0.9f, mx - w / 2, my + d * 0.9f,
            mx - w / 2, my - d * 0.25f, 16);
    p.n--;  // the last point repeats the first
    polyBox(p, 2);
    return 1;
  }
  float c = f.mouth * S * MOUTH_CURVE;
  quadTo(p, mx - w / 2, my - c * 0.3f, mx, my + c, mx + w / 2, my - c * 0.3f, 12);
  polyBox(p, S * MOUTH_THICK);
  return 0;
}

inline bool inBox(const Poly &p, float x, float y) { return x >= p.x0 && x <= p.x1 && y >= p.y0 && y <= p.y1; }
inline float over(float e, float a) { return e + (1 - e) * a; }  // "a" painted over "e", same colour

void drawFace(const Frame &f) {
  uint16_t *buf = canvas.getBuffer();
  // Head motion around the neck: undo it for each pixel to find the face point under it.
  float pivotX = S / 2, pivotY = S * NECK;  // in face pixels; the screen's are these plus OX, OY
  float cr = cosf(-f.rot), sr = sinf(-f.rot);
  float kx = f.sx * f.scale, ky = f.sy * f.scale;
  float tx = f.dx * S, ty = f.dy * S;

  float A = GLOW_DIM + (1 - GLOW_DIM) * f.glow;  // how solid the shapes are
  float ew = S * EYES_WIDTH * f.size;
  float pulse = 1 + f.talk * EYES_TALK_PULSE;
  float eyeCx[2], eyeH[2];
  float eyeCy = S * EYES_Y + f.lookY * S * EYES_REACH_Y;
  Poly brow[2], mouth;
  for (int i = 0; i < 2; i++) {
    int side = i == 0 ? -1 : 1;
    eyeCx[i] = S / 2 + side * S * EYES_APART + f.lookX * S * EYES_REACH_X;
    eyeH[i] = S * EYES_HEIGHT * f.size * (i == 0 ? f.openL : f.openR) * pulse;
    makeBrow(brow[i], eyeCx[i], eyeCy, f, side);
  }
  float oRx = 0, oRy = 0;
  float mx = S / 2 + f.lookX * S * EYES_REACH_X * 0.5f;
  float my = S * MOUTH_Y + f.lookY * S * EYES_REACH_Y * 0.5f;
  int mouthKind = makeMouth(mouth, mx, my, f, oRx, oRy);
  float ringHalf[N_RINGS], ringA[N_RINGS];
  for (int i = 0; i < N_RINGS; i++) {
    ringHalf[i] = S * GLOW_RING_WIDTH * (i + 1) / 2;
    ringA[i] = GLOW_RINGS[i] * f.glow;
  }
  float reach = ringHalf[N_RINGS - 1] + 1;
  bool blushOn = f.blush > BLUSH_FROM && strcmp(state, "offline");
  float blushA = fminf(1.0f, f.blush * BLUSH_STRENGTH * f.glow);
  float browHalf = S * BROWS_THICK / 2, lineHalf = S * MOUTH_THICK / 2;

  for (int y = 0; y < H; y++) {
    for (int x = 0; x < W; x++) {
      float qx = x + 0.5f - OX - pivotX - tx, qy = y + 0.5f - OY - pivotY - ty;
      float px = (qx * cr - qy * sr) / kx + pivotX;
      float py = (qx * sr + qy * cr) / ky + pivotY;

      float e = 0;  // how much eye colour, 0..1
      for (int i = 0; i < 2; i++) {
        if (fabsf(px - eyeCx[i]) > ew / 2 + reach || fabsf(py - eyeCy) > eyeH[i] / 2 + reach + 2) continue;
        float d = eyeDist(px, py, eyeCx[i], eyeCy, ew, eyeH[i], f, i == 0 ? -1 : 1);
        for (int k = 0; k < N_RINGS; k++) e = over(e, ringA[k] * clamp01(ringHalf[k] - fabsf(d) + 0.5f));
        e = over(e, A * clamp01(0.5f - d));
      }
      for (int i = 0; i < 2; i++) {
        if (!inBox(brow[i], px, py)) continue;
        float d = polyDist(brow[i], px, py, false, nullptr);
        e = over(e, A * BROWS_ALPHA * clamp01(browHalf - d + 0.5f));
      }
      if (inBox(mouth, px, py)) {
        float cov;
        if (mouthKind == 2) {
          float nx = (px - mx) / oRx, ny = (py - my) / oRy;
          cov = clamp01(0.5f - (sqrtf(nx * nx + ny * ny) - 1) * fminf(oRx, oRy));
        } else if (mouthKind == 1) {
          bool in;
          float d = polyDist(mouth, px, py, true, &in);
          cov = clamp01(0.5f + (in ? d : -d));
        } else {
          cov = clamp01(lineHalf - polyDist(mouth, px, py, false, nullptr) + 0.5f);
        }
        e = over(e, A * cov);
      }
      float r = f.r * e, g = f.g * e, b = f.b * e;

      if (blushOn) {
        for (int side = -1; side <= 1; side += 2) {
          float bx = (px - (S / 2 + side * S * BLUSH_APART)) / (S * BLUSH_WIDTH);
          float by = (py - S * BLUSH_Y) / (S * BLUSH_HEIGHT);
          float dd = bx * bx + by * by;
          if (dd < 2) {
            float a = blushA * clamp01(0.5f - (sqrtf(dd) - 1) * S * BLUSH_HEIGHT);
            r = lerpf(r, COLOUR_BLUSH[0], a); g = lerpf(g, COLOUR_BLUSH[1], a); b = lerpf(b, COLOUR_BLUSH[2], a);
          }
        }
      }
      uint16_t c = ((uint16_t)fminf(r, 255) & 0xF8) << 8 | ((uint16_t)fminf(g, 255) & 0xFC) << 3 | (uint16_t)fminf(b, 255) >> 3;
      buf[y * W + x] = c;
    }
  }
  oled.drawRGBBitmap(0, 0, buf, W, H);
}

// ---------- the link to Kit's brain ----------
// A helper task on the other core asks Kit's server for the body feed (plain lines,
// see docs/3 Deep Dives/Pod In Depth.md) and hands the lines over through a queue, so the
// face never waits on the network. Pats go up through a second small task.
struct FeedLine { char text[48]; };
QueueHandle_t feedQueue;
TaskHandle_t patTask;
volatile unsigned long lastHeard = 0;   // when the server last answered
bool linked = false;                    // heard from Kit lately, so his brain is in charge
float kitEnergy = 0.5f;                 // his liveliness, from the brain
char restingFace[24] = "neutral";       // the face he wears between moments
unsigned long emotionUntil = 0, talkUntil = 0;
float seenX = 0, seenY = 0;             // where Kit's eyes last saw the person
unsigned long seenAt = 0, followUntil = 0;
const unsigned long FOLLOW_MIN_MS = 8000, FOLLOW_MAX_MS = 25000;  // how long he follows you once he starts
const float FOLLOW_EVERY_CALM_S = 180, FOLLOW_EVERY_LIVELY_S = 45;  // about how often he starts following you
const unsigned long LINK_LOST_MS = 60000;   // on his own again after this long without Kit
const unsigned long EMOTION_HOLD_MS = 6000; // a reply's emotion shows this long, then his resting face

bool kitConfigured() { return strlen(KIT_URL) > 0; }

void feedTask(void *) {
  long last = -1;  // -1: just started, so ask for how Kit is now without old events
  for (;;) {
    if (WiFi.status() != WL_CONNECTED || updating) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
    HTTPClient http;
    String url = String(KIT_URL) + "/api/body/feed";
    if (last >= 0) { url += "?wait=20&after="; url += String(last); }
    http.begin(url);
    http.setTimeout(30000);
    http.addHeader("Authorization", String("Bearer ") + KIT_TOKEN);
    int code = http.GET();
    if (code == 200) {
      String body = http.getString();
      lastHeard = millis();
      int start = 0;
      while (start < (int)body.length()) {
        int end = body.indexOf('\n', start);
        if (end < 0) end = body.length();
        String line = body.substring(start, end);
        start = end + 1;
        if (line.startsWith("last ")) { last = line.substring(5).toInt(); continue; }
        FeedLine f;
        strncpy(f.text, line.c_str(), sizeof(f.text) - 1);
        f.text[sizeof(f.text) - 1] = 0;
        xQueueSend(feedQueue, &f, 0);
      }
    } else {
      static unsigned long lastSaid = 0;
      if (millis() - lastSaid > 30000) {
        Serial.printf("Can't reach Kit at %s (%d)\n", KIT_URL, code);
        lastSaid = millis();
      }
      if (code == 401) Serial.println("Kit says the token is wrong: check KIT_TOKEN in kit_server.h");
      vTaskDelay(pdMS_TO_TICKS(3000));
    }
    http.end();
  }
}

void patSender(void *) {
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    if (WiFi.status() != WL_CONNECTED) continue;
    HTTPClient http;
    http.begin(String(KIT_URL) + "/api/body/touch");
    http.setTimeout(5000);
    http.addHeader("Authorization", String("Bearer ") + KIT_TOKEN);
    http.POST("");
    http.end();
  }
}

void startLink() {
  if (!kitConfigured()) { Serial.println("No Kit server set in kit_server.h: running on my own."); return; }
  feedQueue = xQueueCreate(24, sizeof(FeedLine));
  xTaskCreatePinnedToCore(feedTask, "kit-feed", 8192, nullptr, 1, nullptr, 0);
  xTaskCreatePinnedToCore(patSender, "kit-pat", 6144, nullptr, 1, &patTask, 0);
}

void tellKitPatted() {
  if (linked && patTask) xTaskNotifyGive(patTask);
}

void attend(float x, float y, unsigned long holdMs, bool notice);
float moodEnergy();

// Kit's eyes (the camera) say where the person is, every couple of seconds while
// someone's in view. Someone appearing, or jumping somewhere new, catches his eye.
// Otherwise now and then he follows you for a while; the calm neck still only
// turns for bigger moves, and the eyes follow the rest.
void seePerson(float x, float y, unsigned long now) {
  bool appeared = !seenAt || now - seenAt > 15000;
  bool jumped = fabsf(x - seenX) > 0.6f || fabsf(y - seenY) > 0.5f;
  seenX = x; seenY = y; seenAt = now;
  if (!strcmp(state, "sleeping")) return;
  if (appeared || jumped) {
    attend(x, y, 4000, true);
    followUntil = now + 6000;  // keep an eye on what caught it for a moment
    return;
  }
  if (now >= followUntil) {
    float every = lerpf(FOLLOW_EVERY_CALM_S, FOLLOW_EVERY_LIVELY_S, moodEnergy());
    if (frand(0, 1) < 2.5f / every) followUntil = now + random(FOLLOW_MIN_MS, FOLLOW_MAX_MS);
  }
  if (now < followUntil) attend(x, y, 3000, false);
}

void showFace(const char *name) {
  if (strcmp(state, "sleeping") && findMood(name) >= 0 && strcmp(MOODS[emotion].name, name)) setMood(name);
}

const unsigned long TURN_TO_HOLD_MS = 5000;  // how long he faces someone he's talking to

// One line from Kit's brain.
void applyLine(const char *line, unsigned long now) {
  char word[16] = "", arg[24] = "";
  float num = 0;
  int got = sscanf(line, "%15s %23s %f", word, arg, &num);
  if (got < 2) return;
  if (!strcmp(word, "face")) {
    strncpy(restingFace, arg, sizeof(restingFace) - 1);
    if (now >= emotionUntil) showFace(restingFace);
  } else if (!strcmp(word, "asleep")) {
    bool asleep = arg[0] == '1';
    if (asleep && strcmp(state, "sleeping")) { play("yawn", false); state = "sleeping"; Serial.println("Kit's asleep"); }
    else if (!asleep && !strcmp(state, "sleeping")) { state = "awake"; play("perk_up"); Serial.println("Kit's awake"); }
  } else if (!strcmp(word, "energy")) {
    kitEnergy = clampf(atof(arg), 0, 1);
  } else if (!strcmp(word, "emotion")) {
    if (findMood(arg) >= 0) { setMood(arg); emotionUntil = now + EMOTION_HOLD_MS; }
  } else if (!strcmp(word, "talk")) {
    if (!strcmp(state, "sleeping")) return;
    if (!strcmp(arg, "thinking")) state = "thinking";
    else if (!strcmp(arg, "speaking")) { state = "speaking"; talkUntil = now + (unsigned long)(fmaxf(num, 1) * 1000); }
    else if (!strcmp(arg, "done") && !strcmp(state, "thinking")) state = "awake";
  } else if (!strcmp(word, "look")) {
    seePerson(atof(arg), num, now);
  } else if (!strcmp(word, "turn_to")) {
    // He's talking to someone in the room ("Hi Sam!"): face them while he says it.
    if (strcmp(state, "sleeping")) attend(atof(arg), num, TURN_TO_HOLD_MS, false);
  } else if (!strcmp(word, "gesture")) {
    play(arg, true);
  } else if (!strcmp(word, "fidget")) {
    play(arg, false);
  }
}

// Each frame: take what Kit said, and keep track of whether he's there.
void stepLink(unsigned long now) {
  if (!kitConfigured()) return;
  FeedLine f;
  while (xQueueReceive(feedQueue, &f, 0) == pdTRUE) applyLine(f.text, now);
  bool heard = lastHeard && now - lastHeard < LINK_LOST_MS;
  if (heard != linked) {
    linked = heard;
    Serial.println(linked ? "Linked to Kit's brain" : "Lost Kit: on my own for now");
    if (!linked && strcmp(state, "sleeping")) state = "awake";
  }
  if (!linked) return;
  lastActive = now;  // Kit's brain decides when he sleeps, not the Pod
  if (!strcmp(state, "speaking") && now >= talkUntil) state = "awake";
  if (emotionUntil && now >= emotionUntil) { emotionUntil = 0; showFace(restingFace); }
}

// ---------- the calm neck ----------
// Where the head points now, in look units, so the eyes can lead it.
float headLookX() { return -(headTurn - TURN_CENTRE) / (TURN_SIGN * TURN_RANGE); }
float headLookY() { return (headTilt - TILT_CENTRE) / (TILT_SIGN * TILT_RANGE * 0.6f); }

// How lively he is (0 calm .. 1 lively): sets how often he glances round and how fast he moves.
float moodEnergy() {
  if (strcmp(state, "awake")) return 0.1f;
  if (linked) return kitEnergy;
  const char *m = MOODS[emotion].name;
  const char *lively[] = {"excited", "playful", "surprised", "curious", "happy", "confused", "scared", "proud"};
  const char *calm[] = {"tired", "sleepy", "dreaming", "sad", "focused", "thinking", "relieved", "fond"};
  for (const char *x : lively) if (!strcmp(m, x)) return 0.85f;
  for (const char *x : calm) if (!strcmp(m, x)) return 0.15f;
  return 0.5f;
}

// Whether to glance round now. A small chance each frame, so glances come at random
// but average out to the mood's rate, never sooner than 20 s after the last look.
bool wantsGlance(unsigned long now, float dt) {
  if (now - lastAttention < 20000) return false;
  float every = lerpf(GLANCE_EVERY_CALM_S, GLANCE_EVERY_LIVELY_S, moodEnergy());
  return frand(0, 1) < dt / every;
}

// Pay attention somewhere: x -1 left .. 1 right, y -1 up .. 1 down. The eyes go
// straight there; the head follows if it's far enough and he's held still long enough.
void attend(float x, float y, unsigned long holdMs, bool notice) {
  aimX = clampf(x, -1, 1); aimY = clampf(y, -1, 1);
  aimHoldMs = holdMs; aimUntil = 0; aimNotice = notice;
  if (notice) neckHoldUntil = min(neckHoldUntil, millis() + 1200);  // something new beats a lazy hold, but not instantly
}

void glance() {
  float side = random(2) ? 1 : -1;
  attend(side * frand(0.45f, 1.0f), frand(-0.4f, 0.3f), (unsigned long)frand(3000, 8000), false);
}

// Each frame: decide whether the head should move, then move it smoothly.
void stepNeck(unsigned long now, float dt) {
  bool awake = !strcmp(state, "awake");
  bool attending = aimX != 0 || aimY != 0;
  if (awake && !tour && !attending && wantsGlance(now, dt)) glance();
  bool following = now < followUntil && strcmp(state, "sleeping");
  if (!awake && !aimNotice && !following) { aimX = aimY = 0; aimUntil = 0; }  // talking, asleep: face forward
  if (aimUntil && now >= aimUntil) { aimX = aimY = 0; aimUntil = 0; aimNotice = false; }
  if (attending) lastAttention = now;

  // Where the head wants to be: the attention plus the mood's posture (a droop when sad,
  // head down asleep). The posture only shows if it's bigger than the dead band.
  float wantT = clampf(TURN_CENTRE - TURN_SIGN * TURN_RANGE * aimX, TURN_CENTRE - TURN_RANGE, TURN_CENTRE + TURN_RANGE);
  float wantL = clampf(TILT_CENTRE + TILT_SIGN * TILT_RANGE * (0.6f * aimY + 15 * cur.head_y),
                       TILT_CENTRE - TILT_RANGE, TILT_CENTRE + TILT_RANGE);

  if (!neckMoving && now >= neckHoldUntil &&
      (fabsf(wantT - headTurn) > NECK_DEADBAND_TURN || fabsf(wantL - headTilt) > NECK_DEADBAND_TILT)) {
    float speed = aimNotice ? NECK_SPEED_NOTICE : lerpf(NECK_SPEED_CALM, NECK_SPEED_LIVELY, moodEnergy());
    moveFromT = headTurn; moveFromL = headTilt; moveToT = wantT; moveToL = wantL;
    moveSecs = fmaxf(0.4f, fmaxf(fabsf(wantT - headTurn), fabsf(wantL - headTilt)) / speed);
    moveStart = now; neckMoving = true;
  }
  if (neckMoving) {
    float t = (now - moveStart) / 1000.0f / moveSecs;
    if (t >= 1) {
      t = 1; neckMoving = false;
      neckHoldUntil = now + NECK_HOLD_MS;
      if (aimHoldMs && (aimX != 0 || aimY != 0)) { aimUntil = now + aimHoldMs; aimHoldMs = 0; }
    }
    float k = easeInOut(t);
    headTurn = lerpf(moveFromT, moveToT, k); headTilt = lerpf(moveFromL, moveToL, k);
  } else if (aimHoldMs && (aimX != 0 || aimY != 0) && now >= neckHoldUntil) {
    // Too close to bother turning for: just look with the eyes for a while.
    aimUntil = now + aimHoldMs; aimHoldMs = 0;
  }
}

// ---------- servos ----------
void writeServos() {
  if (!servosOn) { turnServo.attach(PIN_TURN, 500, 2400); tiltServo.attach(PIN_TILT, 500, 2400); servosOn = true; }
  turnServo.writeMicroseconds(500 + (int)(turnPos * 1900 / 180));
  tiltServo.writeMicroseconds(500 + (int)(tiltPos * 1900 / 180));
  servoStill = millis();
}

void stepServos(float dt) {
  if (updating || (!servosEnabled && !tuning)) {
    if (servosOn) { turnServo.detach(); tiltServo.detach(); servosOn = false; }
    return;
  }
  if (tuning) {  // the tuning page has the neck: go there at a steady speed and hold it firmly
    float most = TUNE_SPEED * dt;
    turnPos += clampf(tuneTurn - turnPos, -most, most);
    tiltPos += clampf(tuneTilt - tiltPos, -most, most);
    writeServos();
    return;
  }
  // A real gesture (nod, shake, perk up) rides on top of the resting head.
  float gT = 0, gL = 0;
  if (gesture >= 0 && gestureMovesNeck) {
    gT = -TURN_SIGN * TURN_RANGE * 10 * gestureDX * NECK_GESTURE_SIZE;
    gL = TILT_SIGN * TILT_RANGE * 12 * gestureDY * NECK_GESTURE_SIZE;
  }
  float goalT = clampf(headTurn + gT, TURN_CENTRE - TURN_RANGE, TURN_CENTRE + TURN_RANGE);
  float goalL = clampf(headTilt + gL, TILT_CENTRE - TILT_RANGE, TILT_CENTRE + TILT_RANGE);
  // Light smoothing on top of the eased moves takes the edge off servo steps.
  float k = 1 - expf(-dt / 0.05f);
  bool moving = fabsf(goalT - turnPos) > 0.3f || fabsf(goalL - tiltPos) > 0.3f;
  turnPos = lerpf(turnPos, goalT, k); tiltPos = lerpf(tiltPos, goalL, k);
  if (moving) {
    writeServos();
  } else if (servosOn && millis() - servoStill > 400) {  // let go so they don't buzz
    turnServo.detach(); tiltServo.detach(); servosOn = false;
  }
}

// ---------- the servo tuning page ----------
void command(String cmd);  // below, with the Serial Monitor commands

void loadTuning() {
  prefs.begin("pod", true);
  TURN_CENTRE = prefs.getFloat("turn_c", DEFAULT_TURN_CENTRE);
  TURN_RANGE = prefs.getFloat("turn_r", DEFAULT_TURN_RANGE);
  TURN_SIGN = prefs.getFloat("turn_s", 1);
  TILT_CENTRE = prefs.getFloat("tilt_c", DEFAULT_TILT_CENTRE);
  TILT_RANGE = prefs.getFloat("tilt_r", DEFAULT_TILT_RANGE);
  TILT_SIGN = prefs.getFloat("tilt_s", 1);
  prefs.end();
  headTurn = turnPos = TURN_CENTRE;
  headTilt = tiltPos = TILT_CENTRE;
  Serial.printf("Neck: turn centre %.0f, range %.0f, sign %.0f; tilt centre %.0f, range %.0f, sign %.0f\n",
                TURN_CENTRE, TURN_RANGE, TURN_SIGN, TILT_CENTRE, TILT_RANGE, TILT_SIGN);
}

void saveTuning() {
  prefs.begin("pod", false);
  prefs.putFloat("turn_c", TURN_CENTRE); prefs.putFloat("turn_r", TURN_RANGE); prefs.putFloat("turn_s", TURN_SIGN);
  prefs.putFloat("tilt_c", TILT_CENTRE); prefs.putFloat("tilt_r", TILT_RANGE); prefs.putFloat("tilt_s", TILT_SIGN);
  prefs.end();
  Serial.println("Neck settings saved");
}

// Keep the page's targets inside the neck's range, or anywhere 0..180 with "free" ticked.
void clampTune() {
  float tLo = tuneFree ? 0 : TURN_CENTRE - TURN_RANGE, tHi = tuneFree ? 180 : TURN_CENTRE + TURN_RANGE;
  float lLo = tuneFree ? 0 : TILT_CENTRE - TILT_RANGE, lHi = tuneFree ? 180 : TILT_CENTRE + TILT_RANGE;
  tuneTurn = clampf(tuneTurn, fmaxf(0, tLo), fminf(180, tHi));
  tuneTilt = clampf(tuneTilt, fmaxf(0, lLo), fminf(180, lHi));
}

void takeNeck() {
  if (!tuning) {
    tuning = true;
    tuneTurn = turnPos; tuneTilt = tiltPos;
    Serial.println("The tuning page has the neck");
  }
  tuneUntil = millis() + TUNE_LETGO_MS;
  lastActive = millis();
}

// Hand the neck back to Kit. From /release and when the page goes quiet it eases back to
// centre; before a command (look, nod) it starts from where it is, so the command shows at once.
void giveNeckBack(bool toCentre) {
  if (!tuning) return;
  tuning = false; tuneFree = false;
  headTurn = clampf(turnPos, TURN_CENTRE - TURN_RANGE, TURN_CENTRE + TURN_RANGE);
  headTilt = clampf(tiltPos, TILT_CENTRE - TILT_RANGE, TILT_CENTRE + TILT_RANGE);
  aimX = aimY = 0; aimUntil = 0; aimHoldMs = 0;
  neckMoving = false; neckHoldUntil = millis();
  if (toCentre) {
    moveFromT = headTurn; moveFromL = headTilt; moveToT = TURN_CENTRE; moveToL = TILT_CENTRE;
    moveSecs = fmaxf(0.6f, fmaxf(fabsf(moveToT - moveFromT), fabsf(moveToL - moveFromL)) / NECK_SPEED_CALM);
    moveStart = millis(); neckMoving = true;
  }
  Serial.println("Kit has his neck back");
}

void sendTuneState(const char *note) {
  char buf[420];
  snprintf(buf, sizeof buf,
           "{\"turn\":%.1f,\"tilt\":%.1f,\"tuning\":%s,\"free\":%s,\"tc\":%.1f,\"tr\":%.1f,\"ts\":%d,"
           "\"lc\":%.1f,\"lr\":%.1f,\"ls\":%d,\"state\":\"%s\",\"note\":\"%s\"}",
           turnPos, tiltPos, tuning ? "true" : "false", tuneFree ? "true" : "false",
           TURN_CENTRE, TURN_RANGE, (int)TURN_SIGN, TILT_CENTRE, TILT_RANGE, (int)TILT_SIGN, state, note);
  web.send(200, "application/json", buf);
}

float webArg(const char *name, float fallback) { return web.hasArg(name) ? web.arg(name).toFloat() : fallback; }

void startTuningPage() {
  web.on("/", []() { web.send_P(200, "text/html", TUNING_PAGE); });
  // ?hold=1 while the page is open and has the neck, so it isn't handed back under you
  web.on("/state", []() { if (tuning && web.hasArg("hold")) tuneUntil = millis() + TUNE_LETGO_MS; sendTuneState(""); });
  // raw servo degrees (turn=, tilt=) or a nudge from where it's going (dturn=, dtilt=)
  web.on("/move", []() {
    takeNeck();
    tuneTurn = webArg("turn", tuneTurn) + webArg("dturn", 0);
    tuneTilt = webArg("tilt", tuneTilt) + webArg("dtilt", 0);
    clampTune();
    sendTuneState("");
  });
  web.on("/centre", []() { takeNeck(); tuneTurn = TURN_CENTRE; tuneTilt = TILT_CENTRE; sendTuneState(""); });
  // both servos to 90 and hold, for fitting the horns
  web.on("/fit", []() { takeNeck(); tuneFree = true; tuneTurn = tuneTilt = 90; sendTuneState(""); });
  web.on("/free", []() { takeNeck(); tuneFree = webArg("on", 0) != 0; clampTune(); sendTuneState(""); });
  web.on("/set", []() {
    TURN_CENTRE = clampf(webArg("tc", TURN_CENTRE), 20, 160);
    TURN_RANGE = clampf(webArg("tr", TURN_RANGE), 0, 80);
    TURN_SIGN = webArg("ts", TURN_SIGN) < 0 ? -1 : 1;
    TILT_CENTRE = clampf(webArg("lc", TILT_CENTRE), 20, 160);
    TILT_RANGE = clampf(webArg("lr", TILT_RANGE), 0, 40);
    TILT_SIGN = webArg("ls", TILT_SIGN) < 0 ? -1 : 1;
    if (tuning) clampTune();
    sendTuneState("");
  });
  web.on("/save", []() { saveTuning(); sendTuneState("Saved in the Pod's memory"); });
  web.on("/defaults", []() {
    TURN_CENTRE = DEFAULT_TURN_CENTRE; TURN_RANGE = DEFAULT_TURN_RANGE; TURN_SIGN = 1;
    TILT_CENTRE = DEFAULT_TILT_CENTRE; TILT_RANGE = DEFAULT_TILT_RANGE; TILT_SIGN = 1;
    if (tuning) clampTune();
    sendTuneState("Back to the starting values (not saved yet)");
  });
  web.on("/release", []() { giveNeckBack(true); sendTuneState(""); });
  // any Serial Monitor command (nod, look -1, happy, ...); Kit gets his neck back first
  web.on("/cmd", []() { giveNeckBack(false); command(web.arg("c")); sendTuneState(""); });
  web.onNotFound([]() { web.send(404, "text/plain", "Not here. Try /"); });
  web.begin();
  webReady = true;
  Serial.printf("Servo tuning page: http://%s.local or http://%s\n", POD_NAME, WiFi.localIP().toString().c_str());
}

void stepTuning(unsigned long now) {
  if (webReady) web.handleClient();
  if (tuning) {
    lastActive = now;  // don't doze off mid-tune
    if ((long)(now - tuneUntil) > 0) giveNeckBack(true);
  }
}

// ---------- Wi-Fi uploads ----------
void drawUpdate(float done) {
  canvas.fillScreen(0);
  canvas.setTextColor(0x4FF8);
  canvas.setTextSize(1);
  canvas.setCursor(22, 46);
  canvas.print("New program...");
  canvas.drawRoundRect(14, 62, 100, 12, 6, 0x4FF8);
  canvas.fillRoundRect(16, 64, (int)(96 * done), 8, 4, 0x4FF8);
  oled.drawRGBBitmap(0, 0, canvas.getBuffer(), W, H);
}

void startWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(POD_NAME);
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);  // connects in the background; the face doesn't wait
  ArduinoOTA.setHostname(POD_NAME);
  ArduinoOTA.setPassword(UPLOAD_PASSWORD);
  ArduinoOTA.onStart([]() {
    updating = true;
    tuning = false;
    stepServos(0);  // let the servos go limp while the new program loads
    Serial.println("Receiving a new program over Wi-Fi");
    drawUpdate(0);
  });
  ArduinoOTA.onProgress([](unsigned int got, unsigned int total) {
    static int lastPct = -1;
    int pct = total ? got * 100 / total : 0;
    if (pct != lastPct && pct % 5 == 0) { drawUpdate(pct / 100.0f); lastPct = pct; }
  });
  ArduinoOTA.onEnd([]() { drawUpdate(1); Serial.println("Done, restarting"); });
  ArduinoOTA.onError([](ota_error_t err) { updating = false; Serial.printf("Wi-Fi upload failed (%u)\n", err); });
}

void stepWifi() {
  if (!otaReady && WiFi.status() == WL_CONNECTED) {
    ArduinoOTA.begin();
    otaReady = true;
    Serial.printf("On Wi-Fi as %s (%s). Wi-Fi uploads ready.\n", POD_NAME, WiFi.localIP().toString().c_str());
    startTuningPage();
  }
  if (otaReady) ArduinoOTA.handle();
}

// ---------- input ----------
void wake(unsigned long now) {
  if (!strcmp(state, "sleeping")) { state = "awake"; play("perk_up"); }
  lastActive = now;
}

void command(String cmd) {
  cmd.trim(); cmd.toLowerCase();
  if (cmd.length() == 0) return;
  unsigned long now = millis();
  lastActive = now;
  const char *c = cmd.c_str();
  if (cmd == "help") {
    Serial.println("Moods:"); for (int i = 0; i < N_MOODS; i++) Serial.printf(" %s", MOODS[i].name);
    Serial.println("\nGestures:"); for (int i = 0; i < N_GESTURES; i++) Serial.printf(" %s", GESTURES[i].name);
    Serial.println("\nStates: sleep wake listen think talk offline awake. Attention: look [x [y]] glance. Other: tour still");
    return;
  }
  if (cmd == "tour") { tour = !tour; nextTour = 0; Serial.printf("Mood tour %s\n", tour ? "on" : "off"); return; }
  if (cmd == "glance") { wake(now); glance(); Serial.println("Glancing round"); return; }
  if (cmd == "look" || cmd.startsWith("look ")) {
    float x = frand(-1, 1), y = frand(-0.4f, 0.4f);
    if (cmd.length() > 5) { y = 0; sscanf(c + 5, "%f %f", &x, &y); }
    wake(now); attend(x, y, 4000, true);
    Serial.printf("Something caught his eye at %.2f, %.2f\n", x, y);
    return;
  }
  if (cmd == "still") { servosEnabled = !servosEnabled; Serial.printf("Servos %s\n", servosEnabled ? "on" : "off"); return; }
  if (cmd == "sleep") { state = "sleeping"; Serial.println("Sleeping"); return; }
  if (cmd == "wake") { wake(now); Serial.println("Awake"); return; }
  if (cmd == "listen") { state = "listening"; Serial.println("Listening"); return; }
  if (cmd == "think") { state = "thinking"; Serial.println("Thinking"); return; }
  if (cmd == "talk") { state = "speaking"; Serial.println("Talking"); return; }
  if (cmd == "offline") { state = "offline"; Serial.println("Offline"); return; }
  if (cmd == "awake") { state = "awake"; Serial.println("Awake"); return; }
  if (setMood(c)) { tour = false; if (!strcmp(state, "sleeping")) state = "awake"; return; }
  if (play(c)) { wake(now); return; }
  Serial.println("Unknown. Type help for the list.");
}

void readSerial() {
  if (Serial.available()) command(Serial.readStringUntil('\n'));
}

void checkPat(unsigned long now) {
  static bool was = false;
  bool on = touchRead(PIN_TOUCH) < touchBaseline * 7 / 10;
  if (on && !was && now - lastPat > 500) {
    patCount = (now - lastPat < 4000) ? patCount + 1 : 1;
    lastPat = now;
    tour = false;
    if (!strcmp(state, "sleeping")) {
      Serial.println("Woken by a pat");
      wake(now);
      setMood("fond");
    } else if (patCount >= 3) {  // lots of pats: he giggles
      Serial.println("Pat pat pat!");
      setMood("happy"); play("laugh");
      patCount = 0;
    } else {
      Serial.println("Pat!");
      setMood("fond"); play("wiggle");
    }
    lastActive = now;
    nextIdle = now + 8000;
    emotionUntil = now + EMOTION_HOLD_MS;  // linked: the pat face shows a while before his resting face
    tellKitPatted();
  }
  was = on;
}

// On his own: now and then a new mood or a little move, like the desk face's idle life.
void idleLife(unsigned long now) {
  if (tour) {
    if (now > nextTour) {
      tourIndex = (tourIndex + 1) % N_MOODS;
      setMood(tourIndex);
      nextTour = now + 3500;
    }
    return;
  }
  if (strcmp(state, "awake") || linked) return;  // linked: Kit's brain does the moods and fidgets
  if (now - lastActive > DOZE_AFTER_MS) {
    play("yawn", false); state = "sleeping"; setMood("neutral");
    Serial.println("Dozing off");
    return;
  }
  if (now < nextIdle) return;
  nextIdle = now + random(9000, 22000);
  const char *calm[] = {"neutral", "neutral", "neutral", "curious", "happy", "thinking", "fond", "playful", "focused", "relieved"};
  const char *moves[] = {"look_away", "tilt_head", "peek", "look_up", "shrug", "nod", "wiggle", "double_take"};
  if (gesture < 0 && random(3) == 0) play(moves[random(8)], false);
  else setMood(calm[random(10)]);
}

// ---------- each frame (rig.py tick) ----------
Frame buildFrame(unsigned long now, float dt) {
  Pose target = statePose();
  float a = 1 - expf(-dt / 0.11f);
  for (int i = 0; i < N_POSE; i++) *poseField(cur, i) += (*poseField(target, i) - *poseField(cur, i)) * a;
  const uint8_t *tc = targetColour();
  float ca = 1 - expf(-dt / 0.35f);
  for (int i = 0; i < 3; i++) colour[i] += (tc[i] - colour[i]) * ca;
  const StateRule *rule = stateRule();
  float glowTarget = rule ? rule->glow : 1.0f;
  glowLevel += (glowTarget - glowLevel) * (1 - expf(-dt / 0.4f));

  float g[N_CHANNELS];
  gestureOffsets(now, g);

  // Gaze: quick darts around the pose's look; still when asleep.
  bool sleeping = !strcmp(state, "sleeping");
  if (sleeping) { dartX = dartY = 0; }
  else if (now >= nextDart) {
    bool far = random(4) == 0 && strcmp(state, "listening");
    float rx = far ? 0.9f : 0.35f, ry = far ? 0.6f : 0.25f;
    dartX = frand(-1, 1) * rx; dartY = frand(-1, 1) * ry;
    nextDart = now + random(900, 3700);
  }

  float period = sleeping ? 7.0f : 4.2f;
  breathPhase += dt * 2 * PI / period;
  float breath = sinf(breathPhase);

  float blink = 1;
  if (sleeping || !strcmp(state, "offline")) { if (!blinkStart) nextBlink = now + 1000; }
  else if (!blinkStart && now >= nextBlink) { blinkStart = now; doubleBlink = random(5) == 0; }
  if (blinkStart) {
    float t = (now - blinkStart) / (doubleBlink ? 420.0f : 170.0f);
    if (t >= 1) { blinkStart = 0; nextBlink = now + random(2000, 6200); }
    else blink = 1 - sinf(PI * (doubleBlink ? fmodf(t * 2, 1) : t));
  }

  Frame f;
  float open = fmaxf(0, (cur.open + g[CH_OPEN]) * blink);
  f.openL = open * fmaxf(0, 1 + cur.asym * 0.45f);
  f.openR = open * fmaxf(0, 1 - cur.asym * 0.45f) * (1 - g[CH_WINK]);
  f.squint = clampf(cur.squint + g[CH_SQUINT], 0, 0.95f);
  f.tilt = cur.tilt;
  f.size = cur.size + g[CH_SIZE];
  // Where his attention is but his head isn't yet: the eyes get there first.
  float leadX = clampf(aimX - headLookX(), -0.8f, 0.8f), leadY = clampf(aimY - headLookY(), -0.6f, 0.6f);
  f.lookX = clampf(cur.look_x + dartX + leadX + g[CH_LOOK_X], -1, 1);
  f.lookY = clampf(cur.look_y + dartY + leadY + g[CH_LOOK_Y], -1, 1);
  f.blush = clamp01(cur.blush);
  f.glow = glowLevel;
  f.talk = !strcmp(state, "speaking") ? 0.25f + 0.55f * fabsf(sinf(now / 1000.0f * 11.8f) * sinf(now / 1000.0f * 18.9f + 1)) : 0;
  f.dx = g[CH_DX];
  f.dy = cur.head_y + g[CH_DY] + breath * 0.005f;
  f.rot = cur.head_tilt + g[CH_ROT];
  f.sx = g[CH_SX] * (1 - breath * 0.006f);
  f.sy = g[CH_SY] * (1 + breath * 0.012f);
  f.scale = g[CH_SCALE];
  f.mouth = cur.mouth; f.mouthOpen = cur.mouth_open; f.mouthO = cur.mouth_o;
  f.brow = cur.brow; f.browUp = cur.brow_up;
  f.r = colour[0]; f.g = colour[1]; f.b = colour[2];

  // The neck doesn't follow the darts; stepNeck() decides when the head moves.
  gestureDX = g[CH_DX]; gestureDY = g[CH_DY];
  return f;
}

// ---------- main ----------
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(20);
  SPI.begin(PIN_SCK, -1, PIN_MOSI, PIN_CS);
  oled.begin(16000000);
  oled.fillScreen(0);
  ESP32PWM::allocateTimer(0);
  turnServo.setPeriodHertz(50);
  tiltServo.setPeriodHertz(50);
  long sum = 0;
  for (int i = 0; i < 20; i++) { sum += touchRead(PIN_TOUCH); delay(10); }
  touchBaseline = sum / 20;
  loadTuning();
  randomSeed(esp_random());
  startWifi();
  startLink();
  Serial.println("Kit Pod, Kit 2D face. Type help for commands.");
  lastActive = millis();
  play("perk_up");
}

void loop() {
  static unsigned long last = millis();
  stepWifi();
  if (updating) return;
  unsigned long now = millis();
  float dt = fminf((now - last) / 1000.0f, 0.1f);
  last = now;

  readSerial();
  checkPat(now);
  stepLink(now);
  idleLife(now);
  Frame f = buildFrame(now, dt);
  stepTuning(now);
  if (!tuning) stepNeck(now, dt);
  stepServos(dt);
  drawFace(f);
}
