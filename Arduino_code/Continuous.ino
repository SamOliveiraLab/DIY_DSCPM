#include <Servo.h>
#include <EEPROM.h>

// =========================
// Hardware Setup
// =========================
Servo myservo;
Servo servo;   // spare / unused, kept for compatibility

const int SERVO_PIN = 9;
const int SPARE_SERVO_PIN = 11;

int s1valve = 5;
int s2valve = 6;
int s3valve = 10;

// =========================
// Continuous Servo Settings
// =========================
const int SERVO_NEUTRAL_US = 1492;   // calibrated neutral PWM

// =========================
// Syringe Parameters
// IMPORTANT: keep innerdiameter
// =========================
float innerdiameter = 1.03;   // mm
float innerradius   = 1;
float syringeArea   = 1;   // mm^2


// =========================
// Plunger Travel Parameters
// =========================
float plungerTravelPerDirectionMM = 52.1;

// =========================
// Flow Mode State
// =========================
int flowMode = 0;   // 0 = constant, 1 = pulse, 2 = oscillation, 3 = pulse+oscillation

float pulseRate = 85.0;   // uL/min
float pulseDuty = 0.5;    // fraction, 0 to 1
float pulseFreq = 0.5;    // Hz

unsigned long pulseCycleStartTime = 0;
bool pulseIsOn = true;

// accumulated actual moving time within current direction
unsigned long accumulatedMoveTimeMs = 0;
unsigned long lastMoveUpdateTime = 0;

// =========================
// Oscillation State
// =========================
float oscRate = 110.0;          // mean flowrate, uL/min
float oscFreq = 0.5;            // Hz
float oscAmp  = 10.0;           // amplitude, uL/min

unsigned long oscStartTime = 0;
unsigned long lastOscUpdateMs = 0;

float oscInstantRate = 110.0;
float oscInstantOffset = 57.0;

// =========================
// Pulse + Oscillation State
// =========================
float pulseOscRate  = 110.0;   // mean flowrate, uL/min
float pulseOscPFreq = 0.5;     // pulse frequency, Hz
float pulseOscDuty  = 0.5;     // pulse duty fraction
float pulseOscAmp   = 10.0;    // oscillation amplitude, uL/min
float pulseOscOFreq = 0.5;     // oscillation frequency, Hz

unsigned long pulseOscStartTime = 0;
unsigned long lastPulseOscUpdateMs = 0;

float pulseOscInstantRate = 110.0;
float pulseOscInstantOffset = 57.0;

// =========================
// State Variables
// =========================

int infuse = 1;
int fwd = 0;             // 0 = forward, 1 = reverse
int on = 1;              // 1 = running, 0 = paused/off
int paused = 0;

int valvestate = 1;
int ODremainder = 100;
int pos = 0;

float flowrate = 85.0;         // uL/min
float currentVelocity = 0.0;   // mm/min
float currentOffset = 57;        // PWM offset relative to neutral

unsigned long currentDirectionDurationMs = 5000;
unsigned long lastSwitchTime = 0;
unsigned long pauseStartTime = 0;

// =========================
// EEPROM addresses
// =========================
const int EEPROM_ADDR_ON        = 0;
const int EEPROM_ADDR_FWD       = 1;
const int EEPROM_ADDR_INFUSE    = 2;
const int EEPROM_ADDR_VALVE     = 3;
const int EEPROM_ADDR_FLOW_X100 = 10;

// =========================
// Calibration Data (REAL VALUES)
// flowrate -> PWM offset
// =========================

const int N_CAL = 7;

// These MUST be your real measured flowrates (uL/min)
const float FLOWRATE_POINTS[N_CAL] = {
  85.0,
  97.3,
  112.8,
  128.6,
  149.2,
  173.9,
  205.4
};

// Keep your offsets exactly as calibrated
const int OFFSET_POINTS[N_CAL] = {
  57, 62, 67, 72, 77, 82, 87
};

// =========================
// Save / Load State
// =========================
void saveStateToEEPROM() {
  EEPROM.update(EEPROM_ADDR_ON, on);
  EEPROM.update(EEPROM_ADDR_FWD, fwd);
  EEPROM.update(EEPROM_ADDR_INFUSE, infuse);
  EEPROM.update(EEPROM_ADDR_VALVE, valvestate);

  int flow_x100 = (int)(flowrate * 100.0);
  EEPROM.put(EEPROM_ADDR_FLOW_X100, flow_x100);

  Serial.println(F("[EEPROM] State saved."));
}

void loadStateFromEEPROM() {
  on         = EEPROM.read(EEPROM_ADDR_ON);
  fwd        = EEPROM.read(EEPROM_ADDR_FWD);
  infuse     = EEPROM.read(EEPROM_ADDR_INFUSE);
  valvestate = EEPROM.read(EEPROM_ADDR_VALVE);

  int flow_x100 = 0;
  EEPROM.get(EEPROM_ADDR_FLOW_X100, flow_x100);
  flowrate = flow_x100 / 100.0;

  if (on != 0 && on != 1) on = 1;
  if (fwd != 0 && fwd != 1) fwd = 0;
  if (infuse != 0 && infuse != 1) infuse = 1;
  if (valvestate != 0 && valvestate != 1) valvestate = 1;
  if (flowrate <= 0.0 || flowrate > 10000.0) flowrate = 85.0;
}

float computeOscillationRate() {
  float t = (millis() - oscStartTime) / 1000.0;   // seconds
  float q = oscRate + oscAmp * sin(2.0 * 3.1415926536 * oscFreq * t);
  return q;
}
float computePulseOscillationRate() {
  float t = (millis() - pulseOscStartTime) / 1000.0;   // seconds
  float q = pulseOscRate + pulseOscAmp * sin(2.0 * 3.1415926536 * pulseOscOFreq * t);
  return q;
}

void updateOscillationOutput() {
  unsigned long now = millis();

  // update only every 100 ms
  if (now - lastOscUpdateMs < 100) {
    int pulse = (int)(SERVO_NEUTRAL_US + ((fwd == 0) ? oscInstantOffset : -oscInstantOffset));
    myservo.writeMicroseconds(pulse);
    return;
  }

  lastOscUpdateMs = now;

  float q = computeOscillationRate();

  // do not allow negative or zero rate
  if (q < FLOWRATE_POINTS[0]) q = FLOWRATE_POINTS[0];
  if (q > FLOWRATE_POINTS[N_CAL - 1]) q = FLOWRATE_POINTS[N_CAL - 1];

  float offsetCandidate = flowrateToOffset(q);
  if (offsetCandidate < 0.0) {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
    return;
  }

  oscInstantRate = q;
  oscInstantOffset = offsetCandidate;

  int pulse = (int)(SERVO_NEUTRAL_US + ((fwd == 0) ? oscInstantOffset : -oscInstantOffset));
  myservo.writeMicroseconds(pulse);

  Serial.print(F("[OSC] Rate: "));
  Serial.print(oscInstantRate, 4);
  Serial.print(F(" uL/min, Offset: "));
  Serial.println(oscInstantOffset, 4);
}
void updatePulseOscillationOutput() {
  bool newPulseState = computePulseState();

  if (newPulseState != pulseIsOn) {
    pulseIsOn = newPulseState;
    Serial.print(F("[FLOWD] Pulse state changed: "));
    Serial.println(pulseIsOn ? F("ON") : F("OFF"));
  }

  if (!pulseIsOn) {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
    return;
  }

  unsigned long now = millis();

  // update oscillation only every 100 ms
  if (now - lastPulseOscUpdateMs < 100) {
    int pulse = (int)(SERVO_NEUTRAL_US + ((fwd == 0) ? pulseOscInstantOffset : -pulseOscInstantOffset));
    myservo.writeMicroseconds(pulse);
    return;
  }

  lastPulseOscUpdateMs = now;

  float q = computePulseOscillationRate();

  if (q < FLOWRATE_POINTS[0]) q = FLOWRATE_POINTS[0];
  if (q > FLOWRATE_POINTS[N_CAL - 1]) q = FLOWRATE_POINTS[N_CAL - 1];

  float offsetCandidate = flowrateToOffset(q);
  if (offsetCandidate < 0.0) {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
    return;
  }

  pulseOscInstantRate = q;
  pulseOscInstantOffset = offsetCandidate;

  int pulse = (int)(SERVO_NEUTRAL_US + ((fwd == 0) ? pulseOscInstantOffset : -pulseOscInstantOffset));
  myservo.writeMicroseconds(pulse);

  Serial.print(F("[FLOWD] Inst rate: "));
  Serial.print(pulseOscInstantRate, 4);
  Serial.print(F(" uL/min, Offset: "));
  Serial.println(pulseOscInstantOffset, 4);
}
// =========================
// Physics
// =========================
float flowToVelocity(float Q_uL_per_min) {
  return Q_uL_per_min / syringeArea;
}

unsigned long computeDirectionDurationMs(float travelMM, float velocityMMperMin) {
  if (velocityMMperMin <= 0.0) return 0;

  float durationMin = travelMM / velocityMMperMin;
  float durationMsFloat = durationMin * 60000.0;

  if (durationMsFloat < 1.0) durationMsFloat = 1.0;
  return (unsigned long)(durationMsFloat + 0.5);
}
  bool computePulseState() {
  if (pulseFreq <= 0.0) return false;

  float periodMs = 1000.0 / pulseFreq;
  float onTimeMs = periodMs * pulseDuty;

  if (periodMs <= 0.0) return false;

  unsigned long elapsed = millis() - pulseCycleStartTime;
  float phaseMs = fmod((float)elapsed, periodMs);

  return (phaseMs < onTimeMs);
}

void updateConstantOutput() {
  int pulse = (int)(SERVO_NEUTRAL_US + ((fwd == 0) ? currentOffset : -currentOffset));
  myservo.writeMicroseconds(pulse);
}

void updatePulseOutput() {
  bool newPulseState = computePulseState();

  if (newPulseState != pulseIsOn) {
    pulseIsOn = newPulseState;
    Serial.print(F("[PULSE] State changed: "));
    Serial.println(pulseIsOn ? F("ON") : F("OFF"));
  }

  if (pulseIsOn) {
    int pulse = (int)(SERVO_NEUTRAL_US + ((fwd == 0) ? currentOffset : -currentOffset));
    myservo.writeMicroseconds(pulse);
  } else {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
  }
}

void updateMotorOutput() {
  if (on == 0 || paused == 1) {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
    return;
  }

  if (flowMode == 0) {
    updateConstantOutput();
  } else if (flowMode == 1) {
    updatePulseOutput();
  } else if (flowMode == 2) {
    updateOscillationOutput();
  } else if (flowMode == 3) {
    updatePulseOscillationOutput();
  } else {
    myservo.writeMicroseconds(SERVO_NEUTRAL_US);
  }
}

void updateAccumulatedMoveTime() {
  unsigned long now = millis();

  if (lastMoveUpdateTime == 0) {
    lastMoveUpdateTime = now;
    return;
  }

  unsigned long dt = now - lastMoveUpdateTime;
  lastMoveUpdateTime = now;

  if (flowMode == 0) {
    accumulatedMoveTimeMs += dt;
  } else if (flowMode == 1) {
    if (pulseIsOn) {
      accumulatedMoveTimeMs += dt;
    }
  } else if (flowMode == 2) {
    accumulatedMoveTimeMs += dt;
  } else if (flowMode == 3) {
    if (pulseIsOn) {
      accumulatedMoveTimeMs += dt;
    }
  }
}
// =========================
// Calibration Mapping
// flowrate -> PWM offset
// =========================
float flowrateToOffset(float q) {

  if (q < FLOWRATE_POINTS[0] || q > FLOWRATE_POINTS[N_CAL - 1]) {
    Serial.print(F("ERROR: Flowrate out of calibrated range. Allowed range: "));
    Serial.print(FLOWRATE_POINTS[0], 4);
    Serial.print(F(" to "));
    Serial.print(FLOWRATE_POINTS[N_CAL - 1], 4);
    Serial.println(F(" uL/min"));
    return -1.0;
  }

  // exact match
  for (int i = 0; i < N_CAL; i++) {
    if (fabs(q - FLOWRATE_POINTS[i]) < 0.0001) {
      return OFFSET_POINTS[i];
    }
  }

  // interpolation
  for (int i = 0; i < N_CAL - 1; i++) {
    float Qi  = FLOWRATE_POINTS[i];
    float Qi1 = FLOWRATE_POINTS[i + 1];

    if (q > Qi && q < Qi1) {
      float offset_i  = OFFSET_POINTS[i];
      float offset_i1 = OFFSET_POINTS[i + 1];

      float offsetStar =
        offset_i + ((q - Qi) / (Qi1 - Qi)) * (offset_i1 - offset_i);

      return offsetStar;  
    }
  }

  Serial.println(F("ERROR: Interpolation failed."));
  return -1.0;
}

void recalculateMotionTiming() {
  currentVelocity = flowToVelocity(flowrate);     // for switch timing
  currentOffset = flowrateToOffset(flowrate);     // calibration mapping

  if (currentOffset < 0.0) {
    currentDirectionDurationMs = 0;
    return;
  }

  currentDirectionDurationMs =
    computeDirectionDurationMs(plungerTravelPerDirectionMM, currentVelocity);
}

void applyFlowRate(float newFlowrate) {
  flowrate = newFlowrate;
  recalculateMotionTiming();

  if (currentOffset < 0.0) {
    Serial.println(F("[FLOW] Command rejected."));
    return;
  }

  flowMode = 0;

  accumulatedMoveTimeMs = 0;
  lastMoveUpdateTime = millis();
  lastSwitchTime = millis();

  Serial.println(F("[FLOW] Constant flow applied."));
  Serial.print(F("[FLOW] Requested flow rate: "));
  Serial.println(flowrate, 4);

  Serial.print(F("[FLOW] PWM offset: "));
  Serial.println(currentOffset, 4);

  Serial.print(F("[FLOW] Direction duration: "));
  Serial.println(currentDirectionDurationMs);

  saveStateToEEPROM();
}
// =========================
// Valve / Servo Updates
// =========================
void updateValves() {
  analogWrite(s1valve, valvestate == 0 ? 255 : 0);
  analogWrite(s2valve, valvestate == 1 ? 255 : 0);
  analogWrite(s3valve, 0);
}

void driveServo() {
  updateMotorOutput();
}

void stopOutputs() {
  myservo.writeMicroseconds(SERVO_NEUTRAL_US);
  analogWrite(s1valve, 0);
  analogWrite(s2valve, 0);
  analogWrite(s3valve, 0);
}

// =========================
// Debug Log
// =========================
void printDebugLog() {
  Serial.println(F("----- DEBUG LOG -----"));
  Serial.print(F("FWD: "));
  Serial.println(fwd);

  Serial.print(F("Infuse: "));
  Serial.println(infuse);

  Serial.print(F("ValveState (raw): "));
  Serial.println(valvestate);

  Serial.print(F("Flow mode: "));
  if (flowMode == 0) Serial.println(F("CONSTANT"));
  else if (flowMode == 1) Serial.println(F("PULSE"));
  else if (flowMode == 2) Serial.println(F("OSCILLATION"));
  else if (flowMode == 3) Serial.println(F("PULSE+OSCILLATION"));
  else Serial.println(F("UNKNOWN"));

  Serial.print(F("Flowrate: "));
  Serial.print(flowrate, 4);
  Serial.println(F(" uL/min"));

  Serial.print(F("innerdiameter: "));
  Serial.print(innerdiameter, 4);
  Serial.println(F(" mm"));

  Serial.print(F("Syringe area: "));
  Serial.print(syringeArea, 6);
  Serial.println(F(" mm^2"));

  Serial.print(F("Plunger velocity: "));
  Serial.print(currentVelocity, 6);
  Serial.println(F(" mm/min"));

  Serial.print(F("PWM offset: "));
  Serial.println(currentOffset, 4);

  Serial.print(F("Plunger travel per direction: "));
  Serial.print(plungerTravelPerDirectionMM, 4);
  Serial.println(F(" mm"));

  Serial.print(F("Direction duration: "));
  Serial.print(currentDirectionDurationMs);
  Serial.println(F(" ms"));

  Serial.print(F("Accumulated move time: "));
  Serial.print(accumulatedMoveTimeMs);
  Serial.println(F(" ms"));

  Serial.print(F("Pump ON: "));
  Serial.println(on);

  Serial.print(F("Paused: "));
  Serial.println(paused);

  if (flowMode == 1) {
    Serial.print(F("Pulse rate: "));
    Serial.print(pulseRate, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("Pulse duty fraction: "));
    Serial.println(pulseDuty, 4);

    Serial.print(F("Pulse frequency: "));
    Serial.print(pulseFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("Pulse state: "));
    Serial.println(pulseIsOn ? "ON" : "OFF");
  }
  if (flowMode == 2) {
  Serial.print(F("Osc mean rate: "));
  Serial.print(oscRate, 4);
  Serial.println(F(" uL/min"));

  Serial.print(F("Osc frequency: "));
  Serial.print(oscFreq, 4);
  Serial.println(F(" Hz"));

  Serial.print(F("Osc amplitude: "));
  Serial.print(oscAmp, 4);
  Serial.println(F(" uL/min"));

  Serial.print(F("Osc instantaneous rate: "));
  Serial.print(oscInstantRate, 4);
  Serial.println(F(" uL/min"));

  Serial.print(F("Osc instantaneous offset: "));
  Serial.println(oscInstantOffset, 4);
}
  if (flowMode == 3) {
    Serial.print(F("FLOWD mean rate: "));
    Serial.print(pulseOscRate, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("FLOWD pulse frequency: "));
    Serial.print(pulseOscPFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("FLOWD duty fraction: "));
    Serial.println(pulseOscDuty, 4);

    Serial.print(F("FLOWD oscillation amplitude: "));
    Serial.print(pulseOscAmp, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("FLOWD oscillation frequency: "));
    Serial.print(pulseOscOFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("FLOWD pulse state: "));
    Serial.println(pulseIsOn ? F("ON") : F("OFF"));

    Serial.print(F("FLOWD instant rate: "));
    Serial.print(pulseOscInstantRate, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("FLOWD instant offset: "));
    Serial.println(pulseOscInstantOffset, 4);
  }

  Serial.println(F("----------------------"));
}

// =========================
// Direction Toggle
// =========================
void toggleDirection() {
  fwd = 1 - fwd;
  infuse = 1 - infuse;
  valvestate = (fwd == 0) ? 1 : 0;

  Serial.println(F("[DIR] Direction toggled."));
  Serial.print(F("[DIR] FWD = "));
  Serial.println(fwd);
  Serial.print(F("[DIR] INFUSE = "));
  Serial.println(infuse);
  Serial.print(F("[DIR] ValveState = "));
  Serial.println(valvestate);

  saveStateToEEPROM();
}

void autoSwitchDirectionIfNeeded() {
  if (on == 0 || paused == 1) return;
  if (currentDirectionDurationMs == 0) return;

  if (accumulatedMoveTimeMs >= currentDirectionDurationMs) {
    toggleDirection();
    updateValves();

    accumulatedMoveTimeMs = 0;
    lastSwitchTime = millis();
    lastMoveUpdateTime = millis();

    Serial.println(F("[AUTO] End of plunger travel reached -> switched direction/valves."));
  }
}

// =========================
// Command Handler
// =========================
void handleCommand(const char* cmdRaw) {
  if (cmdRaw == nullptr || cmdRaw[0] == '\0') return;

  Serial.print(F("[CMD] Received: "));
  Serial.println(cmdRaw);

  if (strcmp(cmdRaw, "123") == 0) {
    if (paused == 1) {
      unsigned long pausedDuration = millis() - pauseStartTime;
      lastSwitchTime += pausedDuration;
    }

    on = 1;
    paused = 0;
    updateValves();
    driveServo();
    Serial.println(F("[CMD] Pumps ON"));
    saveStateToEEPROM();
    return;
  }

  if (strcmp(cmdRaw, "0") == 0) {
    on = 0;
    paused = 1;
    pauseStartTime = millis();
    stopOutputs();
    Serial.println(F("[CMD] System OFF. State saved."));
    saveStateToEEPROM();
    return;
  }

  if (strcmp(cmdRaw, "321") == 0) {
    toggleDirection();
    updateValves();
    driveServo();
    lastSwitchTime = millis();
    return;
  }

  if (strcmp(cmdRaw, "456") == 0) {
    printDebugLog();
    return;
  }

  if (strncmp(cmdRaw, "FLOWA,", 6) == 0) {
    float rate = atof(cmdRaw + 6);

    if (rate <= 0.0) {
      Serial.println(F("ERROR: FLOWA rate must be > 0"));
      return;
    }

    applyFlowRate(rate);
    updateValves();
    driveServo();
    return;
  }

    if (strncmp(cmdRaw, "FLOWB,", 6) == 0) {
    char temp[64];
    strncpy(temp, cmdRaw, sizeof(temp) - 1);
    temp[sizeof(temp) - 1] = '\0';

    char* token = strtok(temp, ",");   // "FLOWB"
    token = strtok(NULL, ",");         // rate
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWB format is FLOWB,{rate},{duty},{freq}"));
      return;
    }
    float rate = atof(token);

    token = strtok(NULL, ",");         // duty
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWB format is FLOWB,{rate},{duty},{freq}"));
      return;
    }
    float duty = atof(token);

    token = strtok(NULL, ",");         // freq
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWB format is FLOWB,{rate},{duty},{freq}"));
      return;
    }
    float freq = atof(token);

    // extra field check
    token = strtok(NULL, ",");
    if (token != NULL) {
      Serial.println(F("ERROR: FLOWB format is FLOWB,{rate},{duty},{freq}"));
      return;
    }

    if (rate <= 0.0) {
      Serial.println(F("ERROR: FLOWB rate must be > 0"));
      return;
    }

    if (duty <= 0.0 || duty >= 1.0) {
      Serial.println(F("ERROR: FLOWB duty must be > 0 and < 1"));
      return;
    }

    if (freq <= 0.0) {
      Serial.println(F("ERROR: FLOWB frequency must be > 0"));
      return;
    }

    float offsetCandidate = flowrateToOffset(rate);
    if (offsetCandidate < 0.0) {
      Serial.println(F("[FLOWB] Command rejected."));
      return;
    }

    flowMode = 1;

    pulseRate = rate;
    pulseDuty = duty;
    pulseFreq = freq;

    flowrate = rate;
    currentOffset = offsetCandidate;
    currentVelocity = flowToVelocity(flowrate);
    currentDirectionDurationMs =
      computeDirectionDurationMs(plungerTravelPerDirectionMM, currentVelocity);

    pulseCycleStartTime = millis();
    pulseIsOn = true;

    accumulatedMoveTimeMs = 0;
    lastMoveUpdateTime = millis();
    lastSwitchTime = millis();

    updateValves();
    updateMotorOutput();

    Serial.println(F("[FLOWB] Pulse mode applied."));
    Serial.print(F("[FLOWB] Rate: "));
    Serial.print(pulseRate, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("[FLOWB] Duty fraction: "));
    Serial.println(pulseDuty, 4);

    Serial.print(F("[FLOWB] Frequency: "));
    Serial.print(pulseFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("[FLOWB] PWM offset: "));
    Serial.println(currentOffset, 4);

    Serial.print(F("[FLOWB] Direction move time needed: "));
    Serial.print(currentDirectionDurationMs);
    Serial.println(F(" ms"));
    return;
  }

  if (strncmp(cmdRaw, "FLOWC,", 6) == 0) {
    char temp[64];
    strncpy(temp, cmdRaw, sizeof(temp) - 1);
    temp[sizeof(temp) - 1] = '\0';

    char* token = strtok(temp, ",");   // FLOWC

    token = strtok(NULL, ",");         // rate
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWC format is FLOWC,{rate},{freq},{amp}"));
      return;
    }
    float rate = atof(token);

    token = strtok(NULL, ",");         // freq
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWC format is FLOWC,{rate},{freq},{amp}"));
      return;
    }
    float freq = atof(token);

    token = strtok(NULL, ",");         // amp
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWC format is FLOWC,{rate},{freq},{amp}"));
      return;
    }
    float amp = atof(token);

    token = strtok(NULL, ",");
    if (token != NULL) {
      Serial.println(F("ERROR: FLOWC format is FLOWC,{rate},{freq},{amp}"));
      return;
    }

    if (rate <= 0.0) {
      Serial.println(F("ERROR: FLOWC rate must be > 0"));
      return;
    }

    if (freq <= 0.0) {
      Serial.println(F("ERROR: FLOWC frequency must be > 0"));
      return;
    }

    if (amp < 0.0) {
      Serial.println(F("ERROR: FLOWC amplitude must be >= 0"));
      return;
    }

    // keep whole oscillation inside calibration window
    float qMin = rate - amp;
    float qMax = rate + amp;

    if (qMin < FLOWRATE_POINTS[0] || qMax > FLOWRATE_POINTS[N_CAL - 1]) {
      Serial.print(F("ERROR: Oscillation flow range must stay within calibrated range: "));
      Serial.print(FLOWRATE_POINTS[0], 4);
      Serial.print(F(" to "));
      Serial.print(FLOWRATE_POINTS[N_CAL - 1], 4);
      Serial.println(F(" uL/min"));
      return;
    }

    flowMode = 2;

    oscRate = rate;
    oscFreq = freq;
    oscAmp  = amp;

    flowrate = rate;   // mean rate used for switch timing
    currentVelocity = flowToVelocity(flowrate);
    currentDirectionDurationMs =
      computeDirectionDurationMs(plungerTravelPerDirectionMM, currentVelocity);

    oscStartTime = millis();
    lastOscUpdateMs = 0;
    oscInstantRate = rate;
    oscInstantOffset = flowrateToOffset(rate);

    accumulatedMoveTimeMs = 0;
    lastMoveUpdateTime = millis();
    lastSwitchTime = millis();

    updateValves();
    updateMotorOutput();

    Serial.println(F("[FLOWC] Oscillation mode applied."));
    Serial.print(F("[FLOWC] Mean rate: "));
    Serial.print(oscRate, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("[FLOWC] Frequency: "));
    Serial.print(oscFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("[FLOWC] Amplitude: "));
    Serial.print(oscAmp, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("[FLOWC] Direction move time needed: "));
    Serial.print(currentDirectionDurationMs);
    Serial.println(F(" ms"));
    return;
  }

  if (strncmp(cmdRaw, "FLOWD,", 6) == 0) {
    char temp[64];
    strncpy(temp, cmdRaw, sizeof(temp) - 1);
    temp[sizeof(temp) - 1] = '\0';

    char* token = strtok(temp, ",");   // FLOWD

    token = strtok(NULL, ",");         // rate
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWD format is FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"));
      return;
    }
    float rate = atof(token);

    token = strtok(NULL, ",");         // pfreq
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWD format is FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"));
      return;
    }
    float pfreq = atof(token);

    token = strtok(NULL, ",");         // duty
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWD format is FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"));
      return;
    }
    float duty = atof(token);

    token = strtok(NULL, ",");         // oamp
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWD format is FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"));
      return;
    }
    float oamp = atof(token);

    token = strtok(NULL, ",");         // ofreq
    if (token == NULL) {
      Serial.println(F("ERROR: FLOWD format is FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"));
      return;
    }
    float ofreq = atof(token);

    token = strtok(NULL, ",");
    if (token != NULL) {
      Serial.println(F("ERROR: FLOWD format is FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}"));
      return;
    }

    if (rate <= 0.0) {
      Serial.println(F("ERROR: FLOWD rate must be > 0"));
      return;
    }

    if (pfreq <= 0.0) {
      Serial.println(F("ERROR: FLOWD pulse frequency must be > 0"));
      return;
    }

    if (duty <= 0.0 || duty >= 1.0) {
      Serial.println(F("ERROR: FLOWD duty must be > 0 and < 1"));
      return;
    }

    if (oamp < 0.0) {
      Serial.println(F("ERROR: FLOWD oscillation amplitude must be >= 0"));
      return;
    }

    if (ofreq <= 0.0) {
      Serial.println(F("ERROR: FLOWD oscillation frequency must be > 0"));
      return;
    }

    float qMin = rate - oamp;
    float qMax = rate + oamp;

    if (qMin < FLOWRATE_POINTS[0] || qMax > FLOWRATE_POINTS[N_CAL - 1]) {
      Serial.print(F("ERROR: FLOWD oscillation range must stay within calibrated range: "));
      Serial.print(FLOWRATE_POINTS[0], 4);
      Serial.print(F(" to "));
      Serial.print(FLOWRATE_POINTS[N_CAL - 1], 4);
      Serial.println(F(" uL/min"));
      return;
    }

    flowMode = 3;

    pulseOscRate  = rate;
    pulseOscPFreq = pfreq;
    pulseOscDuty  = duty;
    pulseOscAmp   = oamp;
    pulseOscOFreq = ofreq;

    // reuse existing pulse variables for timing gate
    pulseRate = rate;
    pulseFreq = pfreq;
    pulseDuty = duty;

    flowrate = rate;   // mean rate used for switch timing
    currentVelocity = flowToVelocity(flowrate);
    currentDirectionDurationMs =
      computeDirectionDurationMs(plungerTravelPerDirectionMM, currentVelocity);

    pulseCycleStartTime = millis();
    pulseOscStartTime = millis();
    lastPulseOscUpdateMs = 0;

    pulseIsOn = true;
    pulseOscInstantRate = rate;
    pulseOscInstantOffset = flowrateToOffset(rate);

    accumulatedMoveTimeMs = 0;
    lastMoveUpdateTime = millis();
    lastSwitchTime = millis();

    updateValves();
    updateMotorOutput();

    Serial.println(F("[FLOWD] Pulse + oscillation mode applied."));
    Serial.print(F("[FLOWD] Mean rate: "));
    Serial.print(pulseOscRate, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("[FLOWD] Pulse frequency: "));
    Serial.print(pulseOscPFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("[FLOWD] Duty fraction: "));
    Serial.println(pulseOscDuty, 4);

    Serial.print(F("[FLOWD] Oscillation amplitude: "));
    Serial.print(pulseOscAmp, 4);
    Serial.println(F(" uL/min"));

    Serial.print(F("[FLOWD] Oscillation frequency: "));
    Serial.print(pulseOscOFreq, 4);
    Serial.println(F(" Hz"));

    Serial.print(F("[FLOWD] Direction move time needed: "));
    Serial.print(currentDirectionDurationMs);
    Serial.println(F(" ms"));
    return;
  }

  bool isNumeric = true;
  for (unsigned int i = 0; cmdRaw[i] != '\0'; i++) {
    if (!isDigit(cmdRaw[i]) && cmdRaw[i] != '.') {
      isNumeric = false;
      break;
    }
  }

  if (isNumeric) {
    float rate = atof(cmdRaw);

    if (on != 1) {
      Serial.println(F("ERROR: Pump must be ON to change flow rate"));
      return;
    }

    if (rate <= 0.0) {
      Serial.println(F("ERROR: Numeric flow field must be > 0"));
      return;
    }

    Serial.println(F("[NUMERIC FLOW] Flow field command received."));
    applyFlowRate(rate);
    updateValves();
    driveServo();
    return;
  }

  Serial.print(F("ERROR: Unknown command -> "));
  Serial.println(cmdRaw);
}
// =========================
// Setup
// =========================
void setup() {
  innerradius   = innerdiameter / 2.0;
  syringeArea   = 3.1415926536 * innerradius * innerradius;   // mm^2
  pinMode(s1valve, OUTPUT);
  pinMode(s2valve, OUTPUT);
  pinMode(s3valve, OUTPUT);

  myservo.attach(SERVO_PIN);
  servo.attach(SPARE_SERVO_PIN);

  Serial.begin(9600);
  Serial.setTimeout(50);
  delay(500);

  loadStateFromEEPROM();


  recalculateMotionTiming();
  lastSwitchTime = millis();

  if (on == 1) {
    paused = 0;
    updateValves();
    driveServo();
  } else {
    stopOutputs();
  }


  Serial.println("READY");
  printDebugLog();
}

char cmdBuffer[64];
byte cmdIndex = 0;

unsigned long lastSerialCharTime = 0;
const unsigned long SERIAL_TIMEOUT = 20;
void loop() {

  while (Serial.available() > 0) {

    char c = Serial.read();

    lastSerialCharTime = millis();

    if (c == '\r' || c == '\n') {
      continue;
    }

    if (cmdIndex < sizeof(cmdBuffer) - 1) {
      cmdBuffer[cmdIndex++] = c;
    }
  }

  if (cmdIndex > 0 && millis() - lastSerialCharTime > SERIAL_TIMEOUT) {

    cmdBuffer[cmdIndex] = '\0';

    Serial.print("[AUTO CMD] ");
    Serial.println(cmdBuffer);

    handleCommand(cmdBuffer);

    cmdIndex = 0;
  }

  if (on == 1 && paused == 0) {
    updateValves();
    updateMotorOutput();
    updateAccumulatedMoveTime();
    autoSwitchDirectionIfNeeded();
  } else {
    stopOutputs();
  }

  delay(10);
}
