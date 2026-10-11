// Kit Pod screen test: just the 1.5" OLED, no servos.
// Shows red, green and blue for a second each (checks the wiring and colours),
// then Kit's eyes blinking and glancing left and right.
//
// Board: ESP32 Dev Module. Libraries: "Adafruit SSD1351 library", "Adafruit GFX Library".
// Wiring: VCC -> 3V3, GND -> GND, DIN -> D23, CLK -> D18, CS -> D5, DC -> RX2 (16), RST -> TX2 (17)

#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1351.h>

const int PIN_CS = 5, PIN_DC = 16, PIN_RST = 17, PIN_SCK = 18, PIN_MOSI = 23;
const int W = 128, H = 128;

Adafruit_SSD1351 oled(W, H, &SPI, PIN_CS, PIN_DC, PIN_RST);
GFXcanvas16 canvas(W, H);
uint16_t GLOW;

void drawEyes(int dx, float eyeOpen) {
  canvas.fillScreen(0);
  int h = max(4, (int)(52 * eyeOpen));
  canvas.fillRoundRect(W / 2 - 33 + dx, H / 2 - h / 2, 22, h, min(22, h) / 2, GLOW);
  canvas.fillRoundRect(W / 2 + 11 + dx, H / 2 - h / 2, 22, h, min(22, h) / 2, GLOW);
  oled.drawRGBBitmap(0, 0, canvas.getBuffer(), W, H);
}

void setup() {
  Serial.begin(115200);
  SPI.begin(PIN_SCK, -1, PIN_MOSI, PIN_CS);
  oled.begin(16000000);
  GLOW = oled.color565(127, 227, 255);

  Serial.println("Red");   oled.fillScreen(oled.color565(255, 0, 0)); delay(1000);
  Serial.println("Green"); oled.fillScreen(oled.color565(0, 255, 0)); delay(1000);
  Serial.println("Blue");  oled.fillScreen(oled.color565(0, 0, 255)); delay(1000);

  oled.fillScreen(0);
  oled.setTextColor(GLOW);
  oled.setTextSize(2);
  oled.setCursor(28, 56);
  oled.print("Hi Dan");
  delay(1500);
  Serial.println("Eyes");
}

void loop() {
  static float dx = 0;
  static int target = 0;
  static unsigned long nextBlink = 0, nextLook = 0;
  unsigned long now = millis();

  if (now > nextLook) { target = random(-1, 2) * 18; nextLook = now + random(1200, 3000); }
  dx += (target - dx) * 0.25;

  if (now > nextBlink) {
    for (float o = 1; o > 0.05; o -= 0.3) { drawEyes((int)dx, o); delay(16); }
    for (float o = 0.05; o < 1; o += 0.3) { drawEyes((int)dx, o); delay(16); }
    nextBlink = now + random(2500, 5000);
  }
  drawEyes((int)dx, 1);
  delay(16);
}
