#include <Servo.h>
#include <EEPROM.h>

// --- Hardware Setup ---
Servo myservo;
Servo servo;
int s1valve = 5;
int s2valve = 6;
int s3valve = 10;
int holdvoltage = 80;
int maxangle = 70;
int minangle = 5;

// --- State Variables ---
String incomingByte = "1";
int infuse = 1;
int pos = 5;
int fwd = 0;
int on = 1;
int valvestate = EEPROM.read(3);
int ODremainder = 100;
float amountpumped = 0;

// --- Syringe Parameters ---
float innerdiameter = 0.485;
float mmperdegree = 0.256;
float degper180 = 270;
float volmultiplier = degper180 / 180.0;
float innerradius = innerdiameter / 2;
float uLperdeg = 3.1415926536 * (innerradius * innerradius) * (mmperdegree * volmultiplier);

// --- Flowrate and Delay ---
float flowrate = 1.5;
float minperdeg = uLperdeg / flowrate;
float millisperdeg = minperdeg * 60000;
int newdelay = int(millisperdeg);

// --- Flow calculation ---
void calculatenewdelay(float newflowrate) {
  flowrate = newflowrate;
  uLperdeg = 3.1415926536 * (innerradius * innerradius) * (mmperdegree * volmultiplier);
  minperdeg = uLperdeg / flowrate;
  millisperdeg = minperdeg * 60000;
  newdelay = int(millisperdeg);
}

// --- Struct ---
struct posandfwd {
  int pos;
  int fwd;
};

// --- Motion Logic ---
struct posandfwd IncrementPosition(int pos, int fwd) {
  if (on == 1) {
    if (pos == minangle) {
      valvestate = (infuse == 0) ? 1 : 0;
      fwd = 0;
      pos += 1;
      ODremainder = 100;
    } else if (pos == maxangle) {
      valvestate = (infuse == 0) ? 0 : 1;
      fwd = 1;
      pos -= 1;
      ODremainder = 100;
    } else {
      pos += (fwd == 0) ? 1 : -1;
    }
  }
  return {pos, fwd};
}

// --- Valve + Timing ---
void overdriveAndDelay(bool remainder, int pos, int valvestate, int newdelay) {
  if (remainder) {
    if (ODremainder > newdelay) {
      analogWrite(s1valve, valvestate == 0 ? 255 : 0);
      analogWrite(s2valve, valvestate == 1 ? 255 : 0);
      ODremainder -= newdelay;
      delay(newdelay);
    } else if (ODremainder > 0) {
      if (valvestate == 0) {
        analogWrite(s1valve, 255);
        analogWrite(s2valve, 0);
        delay(ODremainder);
        analogWrite(s1valve, holdvoltage);
        delay(newdelay - ODremainder);
      } else {
        analogWrite(s1valve, 0);
        analogWrite(s2valve, 255);
        delay(ODremainder);
        analogWrite(s2valve, holdvoltage);
        delay(newdelay - ODremainder);
      }
      ODremainder = 0;
    } else {
      delay(newdelay);
    }
  } else {
    if (pos == minangle || pos == maxangle) {
      analogWrite(s3valve, 255);
      delay(10);

      if (valvestate == 0) {
        analogWrite(s1valve, 255);
        analogWrite(s2valve, 0);
        delay(50);
        analogWrite(s3valve, 0);
        delay(100);
        analogWrite(s1valve, holdvoltage);
      } else {
        analogWrite(s1valve, 0);
        analogWrite(s2valve, 255);
        delay(50);
        analogWrite(s3valve, 0);
        delay(100);
        analogWrite(s2valve, holdvoltage);
      }

      if (newdelay > 160) delay(newdelay - 160);
    } else {
      delay(newdelay);
    }
  }
}

// --- Debug Log ---
void printDebugLog() {
  Serial.println("----- DEBUG LOG -----");

  Serial.print("Position: ");
  Serial.println(pos);

  Serial.print("FWD: ");
  Serial.println(fwd);

  Serial.print("Infuse: ");
  Serial.println(infuse);

  Serial.print("ValveState (raw): ");
  Serial.println(valvestate);

  Serial.print("Active Valve: ");
  if (valvestate == 0) {
    Serial.println("S1 ON, S2 OFF");
  } else {
    Serial.println("S2 ON, S1 OFF");
  }

  Serial.print("ODremainder: ");
  Serial.println(ODremainder);

  Serial.print("Flowrate: ");
  Serial.print(flowrate);
  Serial.println(" uL/min");

  Serial.print("Step delay: ");
  Serial.print(newdelay);
  Serial.println(" ms");

  Serial.print("Pump ON: ");
  Serial.println(on);

  Serial.println("----------------------");
}

// --- Command Handler ---
void handleCommand(String cmd) {
  cmd.trim();

  if (cmd == "123") {
    on = 1;
    Serial.println("Pumps ON");
    return;
  }

  if (cmd == "0") {
    EEPROM.write(0, pos);
    EEPROM.write(1, fwd);
    EEPROM.write(2, infuse);
    EEPROM.write(3, valvestate);
    on = 0;
    Serial.println("System OFF. Position saved.");
    return;
  }

  if (cmd == "321") {
    fwd = 1 - fwd;
    infuse = 1 - infuse;
    Serial.println("Direction switched.");
    return;
  }

  if (cmd == "456") {
    printDebugLog();
    return;
  }

  // FLOWA command
  if (cmd.startsWith("FLOWA,")) {
    String rateString = cmd.substring(6);
    rateString.trim();
    float rate = rateString.toFloat();

    if (rate > 0) {
      calculatenewdelay(rate);
      Serial.print("Constant flow set to ");
      Serial.print(flowrate);
      Serial.println(" uL/min");
    } else {
      Serial.println("ERROR: Flow must be > 0");
    }
    return;
  }

  // Numeric flow rate
  bool isNumeric = true;
  for (unsigned int i = 0; i < cmd.length(); i++) {
    if (!isDigit(cmd[i]) && cmd[i] != '.') {
      isNumeric = false;
      break;
    }
  }

  if (isNumeric && cmd.length() > 0) {
    float rate = cmd.toFloat();

    if (rate > 0) {
      calculatenewdelay(rate);
      Serial.print("Flow rate changed to ");
      Serial.print(flowrate);
      Serial.println(" uL/min");
    } else {
      Serial.println("ERROR: Flow must be > 0");
    }
    return;
  }

  Serial.print("ERROR: Unknown command -> ");
  Serial.println(cmd);
}

// --- Main Pump Loop ---
void runPumpLogic() {
  struct posandfwd result = IncrementPosition(pos, fwd);
  pos = result.pos;
  fwd = result.fwd;

  if (on == 1) {
    amountpumped += (infuse == 0) ? uLperdeg : -uLperdeg;
  }

  myservo.write(pos);

  if (newdelay >= 100) {
    overdriveAndDelay(false, pos, valvestate, newdelay);
  } else {
    overdriveAndDelay(true, pos, valvestate, newdelay);
  }
}

// --- Setup ---
void setup() {
  pinMode(s1valve, OUTPUT);
  pinMode(s2valve, OUTPUT);
  pinMode(s3valve, OUTPUT);

  myservo.attach(9);
  servo.attach(11);

  Serial.begin(9600);
  Serial.println("READY");
}

// --- Loop ---
void loop() {
  if (Serial.available()) {
    incomingByte = Serial.readStringUntil('\n');
    handleCommand(incomingByte);
  }

  if (on == 1) {
    runPumpLogic();
  }
}
