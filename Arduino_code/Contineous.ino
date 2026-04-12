#include <Servo.h>
#include <EEPROM.h>

// =========================
// Hardware Setup
// =========================
Servo myservo;
Servo servo;             // unused for now, kept for compatibility
int s1valve = 5;
int s2valve = 6;
int s3valve = 10;
int holdvoltage = 80;
int maxangle = 70;
int minangle = 5;

// =========================
// State Variables
// =========================
String incomingByte = "1";
int infuse = 1;
int pos = 5;
int fwd = 0;             // 0 = forward, 1 = reverse
int on = 1;              // running state (1 = running, 0 = stopped)
int paused = 0;          // paused state
int valvestate = EEPROM.read(3);
int ODremainder = 100;
float amountpumped = 0;

// =========================
// Syringe Parameters
// (kept for volume / future use)
// =========================
float innerdiameter = 0.485;
float mmperdegree   = 0.256;
float degper180     = 270;
float volmultiplier = degper180 / 180.0;
float innerradius   = innerdiameter / 2;
float uLperdeg      = 3.1415926536 * (innerradius * innerradius) *
                      (mmperdegree * volmultiplier);

// =========================
// Flowrate and Delay
// (not currently used to drive servo, but kept)
// =========================
float flowrate      = 1.5;
float minperdeg     = uLperdeg / flowrate;
float millisperdeg  = minperdeg * 60000;
int   newdelay      = int(millisperdeg);

void calculatenewdelay(float newflowrate) {
  flowrate     = newflowrate;
  uLperdeg     = 3.1415926536 * (innerradius * innerradius) *
                 (mmperdegree * volmultiplier);
  minperdeg    = uLperdeg / flowrate;
  millisperdeg = minperdeg * 60000;
  newdelay     = int(millisperdeg);
}

// =========================
/* Continuous Servo Settings */
// =========================
const int SERVO_NEUTRAL_US = 1492;  // Stop signal (calibrated)
// SERVO_SPEED_US no longer used directly, but kept for reference
const int SERVO_SPEED_US   = 65;    // old fixed speed offset

// =========================
// Pump Timing
// =========================
const unsigned long DIRECTION_DURATION_MS = 8000;   // ms per direction
unsigned long lastSwitchTime = 0;

// Pause timing
unsigned long pauseStartTime = 0;

// Speed oscillation timing
unsigned long speedStartTime = 0;   // reference time for oscillation

// =========================
// Helper: reset cycle from t = 0, forward
// =========================
void startPumpCycle() {
  unsigned long now = millis();
  lastSwitchTime = now;   // reset timer to "time zero" for this cycle
  fwd         = 0;        // forward direction
  valvestate  = 1;        // valve state for forward
  paused      = 0;        // ensure not paused
  on          = 1;        // running

  Serial.println("Pump cycle (re)started: t=0, forward, valveState=1");
}

// =========================
// Setup
// =========================
void setup() {
  pinMode(s1valve, OUTPUT);
  pinMode(s2valve, OUTPUT);
  pinMode(s3valve, OUTPUT);

  myservo.attach(9);
  servo.attach(11);  // spare

  Serial.begin(9600);
  Serial.println("Continuous pump with pause/resume/startcycle and speed oscillation...");

  speedStartTime = millis();  // start oscillation timer
  startPumpCycle();           // initial start
}

// =========================
// Command Handler
// Commands (send as lines over Serial):
//   "pause"      -> pause, keep timing frozen
//   "resume"     -> resume from same point in cycle
//   "stop"       -> stop fully
//   "start"      -> continue from current state
//   "startcycle" -> reset to t=0, forward, valve=1, run
// =========================
void handleCommand(String cmd) {
  cmd.trim();

  if (cmd == "pause") {
    if (!paused) {
      paused = 1;
      pauseStartTime = millis();                // record when we paused
      myservo.writeMicroseconds(SERVO_NEUTRAL_US);  // stop servo
      Serial.println("Pump paused.");
    }
  }
  else if (cmd == "resume") {
    if (paused) {
      unsigned long now           = millis();
      unsigned long pausedDuration = now - pauseStartTime;
      // Shift lastSwitchTime forward so we ignore time spent paused
      lastSwitchTime += pausedDuration;

      paused = 0;
      Serial.println("Pump resumed.");
    }
  }
  else if (cmd == "stop") {
    on = 0;
    paused = 0;
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);  // stop servo
    analogWrite(s1valve, 0);
    analogWrite(s2valve, 0);
    analogWrite(s3valve, 0);
    Serial.println("Pump stopped.");
  }
  else if (cmd == "start") {
    on = 1;
    paused = 0;
    Serial.println("Pump started (continue current cycle).");
  }
  else if (cmd == "startcycle") {
    startPumpCycle();  // resets time & direction
  }
  else {
    Serial.print("Unknown command: ");
    Serial.println(cmd);
  }
}

// =========================
// Main Loop
// =========================
void loop() {
  // Handle incoming serial commands
  if (Serial.available()) {
    incomingByte = Serial.readStringUntil('\n');
    handleCommand(incomingByte);
  }

  if (!on) {
    // Fully stopped: ensure servo & valves off
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
    analogWrite(s1valve, 0);
    analogWrite(s2valve, 0);
    analogWrite(s3valve, 0);
    return;
  }

  unsigned long currentTime = millis();

  // If paused, freeze direction & valves; don't advance state or timer
  if (paused) {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);  // stop servo while paused
    analogWrite(s1valve, 0);
    analogWrite(s2valve, 0);
    analogWrite(s3valve, 0);
    return;
  }

  // --- Direction switching (only when not paused) ---
  if (currentTime - lastSwitchTime >= DIRECTION_DURATION_MS) {
    fwd = 1 - fwd;                        // toggle direction
    valvestate = (fwd == 0) ? 1 : 0;      // 1 in forward, 0 in reverse
    lastSwitchTime = currentTime;

    Serial.print("Switched direction! fwd = ");
    Serial.print(fwd);
    Serial.print(", ValveState = ");
    Serial.println(valvestate);
  }

  // --- Drive valves ---
  analogWrite(s1valve, valvestate == 0 ? 255 : 0);
  analogWrite(s2valve, valvestate == 1 ? 255 : 0);
  analogWrite(s3valve, 0);

  // --- Drive continuous servo with oscillating speed ---
  // We want offset to oscillate between 68 and 78 µs
  // Mean = 73, amplitude = 5, period = 2000 ms (2 seconds)
  const float oscillationPeriod = 2000.0;   // ms for full cycle
  const float meanOffset        = 73.0;     // midpoint (between 68 and 78)
  const float oscillationAmp    = 5.0;      // ±5 around mean

  unsigned long elapsed = (millis() - speedStartTime) % (unsigned long)oscillationPeriod;
  float phase = (2.0 * PI * elapsed) / oscillationPeriod;   // 0 → 2π over 2 seconds
  float dynamicSpeedOffset = meanOffset + oscillationAmp * sin(phase);

  // Apply direction (same magnitude, opposite sign)
  int pulse = SERVO_NEUTRAL_US + ((fwd == 0) ? dynamicSpeedOffset : -dynamicSpeedOffset);
  myservo.writeMicroseconds((int)pulse);

  delay(10);
}
