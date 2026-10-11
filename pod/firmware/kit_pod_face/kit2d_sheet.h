// Made by make_sheet.py from kit2d.json ("Kit 2D" v1, look "kit2d_screen"). Don't edit by hand.
#pragma once

const float EYES_APART = 0.201f;
const float EYES_Y = 0.437f;
const float EYES_WIDTH = 0.14f;
const float EYES_HEIGHT = 0.207f;
const float EYES_CORNER = 0.055f;
const float EYES_REACH_X = 0.061f;
const float EYES_REACH_Y = 0.043f;
const float EYES_TALK_PULSE = 0.0f;
const float EYES_SQUINT_LIFT = 1.0f;
const float EYES_SQUINT_ROUND = 1.05f;
const float GLOW_RING_WIDTH = 0.016f;
const float GLOW_BLUR = 0.05f;
const float GLOW_DIM = 0.35f;
const float BROWS_ABOVE = 0.189f;
const float BROWS_WIDTH = 0.122f;
const float BROWS_THICK = 0.016f;
const float BROWS_ARCH = 0.027f;
const float BROWS_SLANT = 0.037f;
const float BROWS_LIFT = 0.037f;
const float BROWS_ALPHA = 0.85f;
const float MOUTH_Y = 0.626f;
const float MOUTH_WIDTH = 0.085f;
const float MOUTH_THICK = 0.015f;
const float MOUTH_CURVE = 0.027f;
const float MOUTH_OPEN = 0.061f;
const float MOUTH_ROUND = 0.049f;
const float MOUTH_TALK = 0.8f;
const float BLUSH_APART = 0.348f;
const float BLUSH_Y = 0.578f;
const float BLUSH_WIDTH = 0.041f;
const float BLUSH_HEIGHT = 0.026f;
const float BLUSH_FROM = 0.2f;
const float BLUSH_STRENGTH = 0.75f;
const float NECK = 0.55f;
const int N_RINGS = 4;
const float GLOW_RINGS[] = {0.1333f, 0.08627f, 0.05098f, 0.02745f};
const uint8_t COLOUR_EYE[3] = {77, 255, 192};
const uint8_t COLOUR_EYE_OFFLINE[3] = {140, 150, 160};
const uint8_t COLOUR_SCREEN[3] = {0, 0, 0};
const uint8_t COLOUR_BEZEL[3] = {0, 0, 0};
const uint8_t COLOUR_BLUSH[3] = {255, 143, 168};

struct Pose { float open, squint, tilt, asym, size, look_x, look_y, blush, head_tilt, head_y, mouth, mouth_open, mouth_o, brow, brow_up; };
const Pose POSE_DEFAULT = {1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.55f, 0.0f, 0.0f, 0.0f, 0.0f};
struct Mood { const char *name; Pose pose; uint8_t colour[3]; };
const Mood MOODS[] = {
  {"neutral", {1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.55f, 0.0f, 0.0f, 0.0f, 0.0f}, {77, 255, 192}},
  {"happy", {1.0f, 0.92f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.8f, 0.0f, -0.006f, 0.55f, 1.0f, 0.0f, 0.0f, 0.0f}, {109, 255, 176}},
  {"curious", {1.0f, 0.0f, 0.0f, 0.0f, 1.048f, 0.3f, 0.0f, 0.0f, 0.16f, 0.0f, 0.55f, 0.0f, 0.5f, 0.0f, 0.6f}, {94, 240, 255}},
  {"thinking", {1.0f, 0.0f, 0.0f, 0.0f, 1.0f, -0.4f, -0.7f, 0.0f, -0.08f, 0.0f, 0.0f, 0.0f, 0.0f, -0.2f, 0.0f}, {111, 184, 255}},
  {"surprised", {1.0f, 0.0f, 0.0f, 0.0f, 1.16f, 0.0f, 0.0f, 0.0f, 0.0f, -0.016f, 0.55f, 0.0f, 1.0f, 0.0f, 1.0f}, {198, 255, 255}},
  {"concerned", {1.0f, 0.0f, 0.7f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.05f, 0.006f, -0.35f, 0.0f, 0.0f, 1.0f, 0.0f}, {143, 208, 255}},
  {"playful", {1.0f, 0.92f, 0.0f, 0.5f, 1.0f, 0.3f, 0.0f, 1.0f, -0.12f, 0.0f, 0.55f, 1.0f, 0.0f, 0.0f, 0.0f}, {125, 255, 216}},
  {"tired", {0.356f, 0.0f, 0.0f, 0.0f, 0.952f, 0.0f, 0.0f, 0.0f, 0.06f, 0.02f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}, {63, 154, 133}},
  {"proud", {1.0f, 0.552f, 0.0f, 0.0f, 1.0f, 0.0f, -0.2f, 0.0f, 0.0f, -0.016f, 0.55f, 0.5f, 0.0f, 0.0f, 0.3f}, {255, 224, 122}},
  {"excited", {1.0f, 0.0f, 0.0f, 0.0f, 1.128f, 0.0f, 0.0f, 1.0f, 0.0f, -0.02f, 0.55f, 1.0f, 0.0f, 0.0f, 0.8f}, {255, 212, 92}},
  {"sad", {1.0f, 0.0f, 1.0f, 0.0f, 1.0f, 0.0f, 0.5f, 0.4f, 0.08f, 0.025f, -0.95f, 0.0f, 0.0f, 1.0f, 0.0f}, {106, 156, 255}},
  {"confused", {0.839f, 0.0f, 0.0f, 0.56f, 1.0f, -0.2f, 0.0f, 0.0f, 0.22f, 0.0f, -0.05f, 0.0f, 0.0f, -0.3f, 0.5f}, {185, 160, 255}},
  {"shy", {1.0f, 0.0f, 0.0f, 0.0f, 0.968f, -0.4f, 0.6f, 1.0f, -0.1f, 0.01f, 0.275f, 0.0f, 0.0f, 0.0f, 0.0f}, {255, 176, 200}},
  {"grumpy", {1.0f, 0.0f, -1.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.01f, -0.65f, 0.0f, 0.0f, -1.0f, 0.0f}, {255, 122, 92}},
  {"focused", {1.0f, 0.0f, -0.5f, 0.0f, 0.968f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, -0.3f, 0.0f}, {64, 255, 208}},
  {"relieved", {0.586f, 0.276f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.01f, 0.55f, 0.2f, 0.0f, 0.3f, 0.0f}, {159, 255, 216}},
  {"fond", {1.0f, 0.644f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.8f, 0.1f, 0.0f, 0.55f, 0.3f, 0.0f, 0.3f, 0.0f}, {255, 179, 217}},
  {"scared", {1.0f, 0.0f, 0.35f, 0.0f, 0.976f, 0.0f, -0.4f, 0.0f, 0.0f, 0.0f, -0.35f, 0.0f, 0.25f, 1.0f, 0.0f}, {143, 168, 255}},
  {"sleepy", {0.08f, 0.0f, 0.0f, 0.0f, 0.968f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.33f, 0.0f, 0.0f, 0.0f, 0.0f}, {63, 92, 255}},
  {"dreaming", {0.08f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.6f, 0.0f, 0.0f, 0.55f, 0.15f, 0.0f, 0.0f, 0.2f}, {169, 139, 255}},
};
const int N_MOODS = sizeof(MOODS) / sizeof(MOODS[0]);

struct StateRule { const char *name; const char *pose; const char *only_from; float glow;
  float add[15]; bool has_set[15]; float set[15]; };
const StateRule STATES[] = {
  {"sleeping", "sleepy", nullptr, 0.45f, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}, {false, false, false, false, false, false, true, false, false, true, false, false, false, false, false}, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.4f, 0.0f, 0.0f, 0.03f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}},
  {"offline", "tired", nullptr, 0.3f, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}, {false, false, false, false, false, false, false, true, false, false, false, false, false, false, false}, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}},
  {"thinking", "thinking", "neutral", 1.0f, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}, {false, false, false, false, false, false, false, false, false, false, false, false, false, false, false}, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}},
  {"listening", nullptr, nullptr, 1.0f, {0.1f, 0.0f, 0.0f, 0.0f, 0.03f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}, {false, false, false, false, false, false, false, false, false, false, false, false, false, false, false}, {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}},
};
const int N_STATES = sizeof(STATES) / sizeof(STATES[0]);

enum Channel { CH_DX, CH_DY, CH_ROT, CH_SX, CH_SY, CH_SCALE, CH_LOOK_X, CH_LOOK_Y, CH_OPEN, CH_SQUINT, CH_SIZE, CH_WINK, N_CHANNELS };
enum ShapeType { SH_NONE, SH_BUMP, SH_HOLD, SH_SIN, SH_ABS_SIN, SH_LINE, SH_JOLT };
struct Shape { uint8_t type; float a, b, c; };
struct Term { uint8_t channel; float amount; Shape shapes[3]; };
struct Gesture { const char *name; float seconds; int first, count; };
const Term TERMS[] = {
  {CH_DY, 0.035f, {{SH_BUMP, 0.05f, 0.4f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, 0.025f, {{SH_BUMP, 0.45f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, 0.5f, {{SH_BUMP, 0.0f, 0.85f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DX, 0.04f, {{SH_SIN, 4.0f, 0.0f, 0.0f}, {SH_LINE, 1.0f, -1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_X, -0.7f, {{SH_SIN, 4.0f, 0.0f, 0.0f}, {SH_LINE, 1.0f, -1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.28f, {{SH_HOLD, 0.25f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, 0.1f, {{SH_HOLD, 0.25f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, -0.2f, {{SH_HOLD, 0.25f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, -0.08f, {{SH_BUMP, 0.0f, 0.18f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, 0.1f, {{SH_BUMP, 0.15f, 0.6f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SX, 0.06f, {{SH_BUMP, 0.0f, 0.18f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SX, -0.05f, {{SH_BUMP, 0.15f, 0.6f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.045f, {{SH_BUMP, 0.15f, 0.7f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, 0.25f, {{SH_BUMP, 0.12f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, 0.045f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, -0.06f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SX, 0.03f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, -0.35f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, 0.6f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.06f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_X, 0.95f, {{SH_HOLD, 0.15f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, -0.55f, {{SH_HOLD, 0.15f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, -0.07f, {{SH_HOLD, 0.15f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DX, 0.02f, {{SH_HOLD, 0.15f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.03f, {{SH_BUMP, 0.1f, 0.6f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.12f, {{SH_SIN, 2.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.13f, {{SH_SIN, 6.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.45f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.06f, {{SH_ABS_SIN, 2.0f, 0.0f, 0.0f}, {SH_LINE, 1.0f, -0.4f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, -0.07f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, 0.07f, {{SH_ABS_SIN, 2.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SX, 0.05f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SX, -0.05f, {{SH_ABS_SIN, 2.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.45f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SCALE, 0.13f, {{SH_HOLD, 0.25f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, 0.12f, {{SH_HOLD, 0.25f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_WINK, 1.0f, {{SH_HOLD, 0.2f, 0.65f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.3f, {{SH_HOLD, 0.2f, 0.65f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, -0.06f, {{SH_HOLD, 0.2f, 0.65f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, 0.012f, {{SH_SIN, 10.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.8f, {{SH_BUMP, 0.0f, 1.0f, 3.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.04f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, -0.3f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.02f, {{SH_BUMP, 0.0f, 0.35f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, 0.03f, {{SH_BUMP, 0.3f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, 0.05f, {{SH_BUMP, 0.0f, 0.35f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, -0.05f, {{SH_BUMP, 0.3f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, 0.1f, {{SH_BUMP, 0.0f, 0.35f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, -0.4f, {{SH_BUMP, 0.3f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, -0.3f, {{SH_BUMP, 0.0f, 0.35f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, 0.4f, {{SH_BUMP, 0.3f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SCALE, -0.12f, {{SH_JOLT, 0.1f, 0.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.03f, {{SH_JOLT, 0.1f, 0.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, 0.4f, {{SH_JOLT, 0.1f, 0.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SIZE, 0.12f, {{SH_JOLT, 0.1f, 0.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DX, 0.01f, {{SH_SIN, 14.0f, 0.0f, 0.0f}, {SH_JOLT, 0.1f, 0.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SY, 0.09f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SX, -0.04f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.6f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, -0.5f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, -0.08f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.02f, {{SH_HOLD, 0.3f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_X, 0.8f, {{SH_BUMP, 0.0f, 0.3f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, -0.05f, {{SH_BUMP, 0.0f, 0.3f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, 0.35f, {{SH_BUMP, 0.35f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SIZE, 0.1f, {{SH_BUMP, 0.35f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SCALE, 0.06f, {{SH_BUMP, 0.35f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.02f, {{SH_BUMP, 0.35f, 0.55f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.15f, {{SH_SIN, 8.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.015f, {{SH_ABS_SIN, 8.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.5f, {{SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DX, 0.015f, {{SH_SIN, 4.0f, 0.0f, 0.0f}, {SH_BUMP, 0.0f, 1.0f, 0.0f}, {SH_NONE, 0, 0, 0}}},
  {CH_DX, 0.05f, {{SH_HOLD, 0.25f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, 0.12f, {{SH_HOLD, 0.25f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_X, 0.9f, {{SH_HOLD, 0.25f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_OPEN, -0.15f, {{SH_HOLD, 0.25f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_SQUINT, 0.2f, {{SH_HOLD, 0.25f, 0.75f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_X, -0.5f, {{SH_HOLD, 0.2f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_LOOK_Y, -0.9f, {{SH_HOLD, 0.2f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_ROT, -0.06f, {{SH_HOLD, 0.2f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
  {CH_DY, -0.01f, {{SH_HOLD, 0.2f, 0.8f, 0.0f}, {SH_NONE, 0, 0, 0}, {SH_NONE, 0, 0, 0}}},
};
const Gesture GESTURES[] = {
  {"nod", 0.9f, 0, 3},
  {"shake", 1.0f, 3, 2},
  {"tilt_head", 1.5f, 5, 3},
  {"perk_up", 0.9f, 8, 6},
  {"droop", 1.6f, 14, 6},
  {"look_away", 1.7f, 20, 4},
  {"shrug", 1.2f, 24, 2},
  {"wave", 1.3f, 26, 2},
  {"bounce", 1.0f, 28, 6},
  {"lean_in", 1.6f, 34, 2},
  {"wink", 0.8f, 36, 3},
  {"laugh", 1.2f, 39, 4},
  {"sigh", 2.0f, 43, 8},
  {"startle", 1.3f, 51, 5},
  {"yawn", 2.2f, 56, 6},
  {"double_take", 1.4f, 62, 6},
  {"wiggle", 1.4f, 68, 4},
  {"peek", 1.8f, 72, 5},
  {"look_up", 1.8f, 77, 4},
};
const int N_GESTURES = sizeof(GESTURES) / sizeof(GESTURES[0]);
