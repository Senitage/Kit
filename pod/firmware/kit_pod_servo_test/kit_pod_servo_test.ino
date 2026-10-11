// Kit Pod servo test: moves each servo on its own so you can check both work.
// Order: both go to centre, turn servo looks left and right, tilt servo nods up and down, repeat.
// Servos let go between rounds so they don't buzz.
//
// Board: ESP32 Dev Module. Library: "ESP32Servo".
// Wiring: turn servo orange -> D13, tilt servo orange -> D14, both red -> VIN, both brown -> GND.
// Open Tools > Serial Monitor at 115200 to see which move is happening.

#include <ESP32Servo.h>

const int PIN_TURN = 13, PIN_TILT = 14;
const int CENTRE = 90;

Servo turnServo, tiltServo;

void slowMove(Servo &s, int from, int to) {
  int step = from < to ? 1 : -1;
  for (int a = from; a != to; a += step) { s.write(a); delay(12); }
  s.write(to);
}

void setup() {
  Serial.begin(115200);
  ESP32PWM::allocateTimer(0);
  turnServo.setPeriodHertz(50);
  tiltServo.setPeriodHertz(50);
}

void loop() {
  turnServo.attach(PIN_TURN, 500, 2400);
  tiltServo.attach(PIN_TILT, 500, 2400);

  Serial.println("Both to centre (90)");
  turnServo.write(CENTRE); tiltServo.write(CENTRE); delay(1000);

  Serial.println("Turn servo: left, right, centre");
  slowMove(turnServo, CENTRE, CENTRE - 40); delay(400);
  slowMove(turnServo, CENTRE - 40, CENTRE + 40); delay(400);
  slowMove(turnServo, CENTRE + 40, CENTRE); delay(800);

  Serial.println("Tilt servo: up, down, centre");
  slowMove(tiltServo, CENTRE, CENTRE - 20); delay(400);
  slowMove(tiltServo, CENTRE - 20, CENTRE + 20); delay(400);
  slowMove(tiltServo, CENTRE + 20, CENTRE); delay(800);

  Serial.println("Resting");
  turnServo.detach(); tiltServo.detach();
  delay(2000);
}
