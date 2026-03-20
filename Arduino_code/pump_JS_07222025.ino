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

void calculatenewdelay(float newflowrate) {
  flowrate = newflowrate;
  uLperdeg = 3.1415926536 * (innerradius * innerradius) * (mmperdegree * volmultiplier); 
  minperdeg = uLperdeg / flowrate;
  millisperdeg = minperdeg * 60000;
  newdelay = int(millisperdeg);
}

struct posandfwd {
  int pos;
  int fwd;
};

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

void handleCommand(String cmd) {
  cmd.trim();

  if (cmd.toInt() == 0) {
    EEPROM.write(0, pos);
    EEPROM.write(1, fwd);
    EEPROM.write(2, infuse);
    EEPROM.write(3, valvestate);
    on = 0;
    Serial.println("System OFF. Position saved.");
  } else if (cmd.toInt() == 123) {
    on = 1;
    Serial.println("Pumps ON");
  } else if (cmd.toInt() == 456) {
    Serial.println("LOG:");
    Serial.print("Position: "); Serial.println(pos);
    Serial.print("FWD: "); Serial.println(fwd);
    Serial.print("ValveState: "); Serial.println(valvestate);
    Serial.print("ODremainder: "); Serial.println(ODremainder);
  } else if (cmd.toInt() == 321) {
    fwd = 1 - fwd;
    infuse = 1 - infuse;
    Serial.println("Direction switched.");
  } else {
    calculatenewdelay(cmd.toFloat());
    Serial.print("Flow rate changed to ");
    Serial.print(flowrate);
    Serial.println(" uL/min");
  }
}

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

void setup() {
  pinMode(s1valve, OUTPUT);
  pinMode(s2valve, OUTPUT);
  pinMode(s3valve, OUTPUT);
  myservo.attach(9);
  servo.attach(11);
  Serial.begin(9600);
  Serial.println("READY"); // For Python handshake
}

void loop() {
  if (Serial.available()) {
    incomingByte = Serial.readStringUntil('\n');
    handleCommand(incomingByte);
  }

  if (on == 1) {
    runPumpLogic();
  }
}
