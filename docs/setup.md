---
layout: default
title: Setup & Installation
---

# Setup & Installation

[Back to Home](./)

---

## Requirements

- Python 3.8+
- PyQt5
- pyserial
- Arduino board with the pump firmware loaded

## Install Dependencies

```bash
pip install PyQt5 pyserial
```

## Flash the Arduino

1. Open `Arduino_code/pump_JS_07222025.ino` in the Arduino IDE.
2. Upload it to your board.
3. The firmware uses:
   - **Pins 9, 11** for servo motors
   - **Pins 5, 6, 10** for solenoid valves
   - **Baud rate:** 9600

## Run from Source

```bash
cd "Python code"
python GUI.py
```

## Run the Packaged App (macOS)

If you have the pre-built app:

- **Double-click** `dist/PumpGUI.app`, or
- **From terminal:** `./dist/PumpGUI`

No Python installation required for the packaged version.

---

[Back to Home](./)
