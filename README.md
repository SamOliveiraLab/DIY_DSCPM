# DIY Dual Syringe Pump

A PyQt5 desktop application for controlling dual syringe pumps via Arduino over USB serial. Supports multiple pump connections, four flow behavior modes, scheduled command sequences, and experiment file generation.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Project Structure](#project-structure)
3. [Setup](#setup)
4. [Running the Application](#running-the-application)
5. [GUI Overview](#gui-overview)
6. [Connecting Pumps](#connecting-pumps)
7. [Pump Controls](#pump-controls)
8. [Flow Behaviors](#flow-behaviors)
9. [Pause / Resume / Restart](#pause--resume--restart)
10. [Text File Scheduling](#text-file-scheduling)
11. [Create Experiment Dialog](#create-experiment-dialog)
12. [Text File Format](#text-file-format)
13. [Arduino Command Protocol](#arduino-command-protocol)
14. [Troubleshooting](#troubleshooting)

---

## Requirements

- Python 3.8+
- PyQt5
- pyserial
- Arduino board with the DSCPM firmware loaded (`pump_JS_07222025.ino`)

Install Python dependencies:

```bash
pip install PyQt5 pyserial
```

## Project Structure

```
DSCPM_v2/
├── Arduino_code/
│   └── pump_JS_07222025.ino    # Arduino firmware for pump control
├── Python code/
│   ├── GUI.py                  # Entry point - launches the application
│   ├── pump_app.py             # Main window, all GUI logic and widgets
│   ├── arduino_cmds.py         # Serial communication wrapper
│   ├── autoport.py             # USB port auto-detection and connection
│   └── pump_render.png         # Pump image displayed in the GUI
└── README.md
```

## Setup

1. **Flash the Arduino**: Open `Arduino_code/pump_JS_07222025.ino` in the Arduino IDE and upload it to your board. The firmware uses pins 9 and 11 for servos and pins 5, 6, 10 for solenoid valves. Baud rate is 9600.

2. **Connect hardware**: Plug the Arduino into your computer via USB. Note the serial number or device path if you plan to use manual connection.

3. **Install dependencies**: Run `pip install PyQt5 pyserial` in your Python environment.

## Running the Application

```bash
cd "Python code"
python GUI.py
```

The Pump GUI window will open.

---

## GUI Overview

The interface is organized into rows from top to bottom:

| Row | Section | Purpose |
|-----|---------|---------|
| 0 | Pump Image | Visual reference of the pump hardware |
| 1 | Multi Pump Connect | Connect multiple pumps by entering serial numbers |
| 2 | Connect / Serial | Auto-connect or manually enter a serial number / device path |
| 3 | Flowrate Quick Adjust | Type a number (0–40) to change flow rate on the fly |
| 4 | On/Off + Direction | Turn the pump on/off and toggle flow direction |
| 5 | Flow Behavior | Select a flow mode, enter parameters, and apply |
| 6 | Pause / Resume / Restart | Control scheduled command execution |
| 7 | File Buttons | Create experiment, upload/change/run/exit text files |
| 8 | File Labels | Shows the currently selected file name |
| 9 | File Contents Display | Human-readable preview of the loaded command file |

---

## Connecting Pumps

### Auto Connect

Click **Auto Connect**. The software scans USB ports and connects to the first likely Arduino device. The button turns green on success.

### Manual Connect

Type a USB serial number (e.g. `054433A493735191B7D8`) or a device path (e.g. `/dev/cu.usbmodem1101`) into the serial input field and press Enter.

### Multiple Pumps

1. Enter the number of pumps (1–10) in the "Connect multiple pumps" field and press Enter.
2. A popup window appears - enter the serial number for each pump.
3. Click **Collect Serial #s**. The software connects to each Arduino and adds them to the pump dropdown.
4. Use the dropdown to switch between connected pumps.

---

## Pump Controls

### On/Off

- Click **Pump: OFF** to turn the pump on. Sends `123` to the Arduino.
- Click **Pump: ON** to turn it off. Sends `0` to the Arduino.
- The button changes color: green = on, red = off.

### Direction

- Click the **Direction** button to toggle between forward (`-->`) and backward (`<--`). Sends `321` to the Arduino.
- Direction only toggles when the pump is on.

### Quick Flowrate Adjust

Type an integer (0–40) in the flowrate field and press Enter. This sends the number directly to the Arduino, which recalculates the servo delay for that flow rate in uL/min.

---

## Flow Behaviors

The **Flow Behavior** section provides four modes. Select a mode from the dropdown, fill in the visible parameters, then click **Apply Flow** to send the command.

### Constant

Steady flow in one direction.

| Parameter | Description |
|-----------|-------------|
| Flow Rate (uL/min) | 0–40 |

Command sent: `FLOWA,{rate}`

### Pulse

Intermittent on/off bursts.

| Parameter | Description |
|-----------|-------------|
| Flow Rate (uL/min) | 0–40 |
| Duty Cycle (0–1) | Fraction of each cycle the pump is active |
| Pulse Freq (Hz) | How many cycles per second |

Command sent: `FLOWB,{rate},{duty},{freq}`

### Oscillation

Back-and-forth flow.

| Parameter | Description |
|-----------|-------------|
| Flow Rate (uL/min) | 0–40 |
| Osc Freq (Hz) | Oscillation frequency |
| Osc Amplitude | Amplitude of the oscillation |

Command sent: `FLOWC,{rate},{freq},{amplitude}`

### Pulse of Oscillation

Pulsed bursts of oscillatory flow - combines both behaviors.

| Parameter | Description |
|-----------|-------------|
| Flow Rate (uL/min) | 0–40 |
| Pulse Freq (Hz) | Frequency of the pulse envelope |
| Duty Cycle (0–1) | Fraction of each pulse cycle that is active |
| Osc Amplitude | Amplitude of the oscillation within each pulse |
| Osc Freq (Hz) | Frequency of the oscillation within each pulse |

Command sent: `FLOWD,{rate},{pulse_freq},{duty},{osc_amplitude},{osc_freq}`

> **Note**: The Arduino firmware must be updated to parse and execute these `FLOW` commands. The current firmware only handles constant flow via numeric flow rate values.

---

## Pause / Resume / Restart

These buttons control scheduled command execution (from text files or generated experiments):

| Button | Action |
|--------|--------|
| **Pause** | Sends `0` to stop the pump. Freezes the command scheduler. All remaining command times are shifted forward so relative timing is preserved on resume. |
| **Resume** | Sends `123` to restart the pump. Unfreezes the scheduler and continues from where it left off. |
| **Restart Cycle** | Stops the current execution entirely, recalculates all command times from the original delays, and starts the full sequence over from the beginning. |

---

## Text File Scheduling

You can run pre-written command sequences from `.txt` files.

### Upload a File

Click **Upload .txt file**, browse to your file, and select it. The file name appears in the label and its contents are displayed in the preview area.

### Run a File

Click **Run .txt file**. The software parses the file, matches serial numbers to connected boards, and begins executing commands on a background thread at the scheduled times.

- If a worker is already running, new commands are merged into the existing schedule.
- If a serial number in the file doesn't match any connected board but only one board is connected, it falls back to that board.

### Change File

Click **Change current file** to cycle through previously uploaded files.

### Exit / Stop

Click **Exit current file** to kill the running scheduler, stop the pump, and clear all scheduled commands.

---

## Create Experiment Dialog

Click the purple **Create Experiment** button to open a dialog for building command sequences visually.

### Steps

1. **Select a pump** from the dropdown (uses connected pump names).
2. **Enter the time** in seconds from the start of the experiment.
3. **Choose a behavior**: Turn On, Turn Off, Change Direction, Constant, Pulse, Oscillation, or Pulse of Oscillation.
4. **Fill in the parameters** that appear for the selected behavior.
5. Click **Add Step**. The step appears in the table below.
6. Repeat for all steps in your experiment.

### Managing Steps

- Select a row in the table and click **Remove Selected** to delete it.
- Steps are sorted by time when the file is generated.

### Generating the File

Click **Generate & Save File**. A save dialog appears - choose a location and filename. The software:

1. Writes the `.txt` file to disk in the standard command format.
2. Loads it as the current file in the main GUI.
3. Displays the parsed commands in the file contents preview.

You can then click **Run .txt file** to execute the experiment immediately.

---

## Text File Format

Command files use this format, with entries separated by `%%%%%%%%%`:

```
SERIAL*********COMMAND#########DELAY%%%%%%%%%SERIAL*********COMMAND#########DELAY
```

| Field | Description |
|-------|-------------|
| `SERIAL` | The Arduino's USB serial number (e.g. `054433A493735191B7D8`) |
| `COMMAND` | Any valid command string (see table below) |
| `DELAY` | Time in seconds from the start of execution |

### Example File

```
054433A493735191B7D8*********123#########0%%%%%%%%%054433A493735191B7D8*********FLOWA,10.0#########2%%%%%%%%%054433A493735191B7D8*********FLOWB,15.0,0.5,2.0#########30%%%%%%%%%054433A493735191B7D8*********0#########60
```

This sequence:
1. At 0s - Turn pump on
2. At 2s - Constant flow at 10 uL/min
3. At 30s - Switch to pulse mode (15 uL/min, 50% duty, 2 Hz)
4. At 60s - Turn pump off

---

## Arduino Command Protocol

Communication runs at **9600 baud**. The Arduino sends `READY` on startup; Python waits for this before proceeding.

### Commands (Python to Arduino)

| Command | Action |
|---------|--------|
| `0` | Turn pump off. Saves position to EEPROM. |
| `123` | Turn pump on. |
| `321` | Toggle flow direction. |
| `456` | Request status log (position, direction, valve state). |
| Any float (e.g. `10.5`) | Set flow rate in uL/min. Recalculates servo delay. |
| `FLOWA,{rate}` | Constant flow mode (firmware update required). |
| `FLOWB,{rate},{duty},{freq}` | Pulse mode (firmware update required). |
| `FLOWC,{rate},{freq},{amp}` | Oscillation mode (firmware update required). |
| `FLOWD,{rate},{pfreq},{duty},{oamp},{ofreq}` | Pulse of oscillation mode (firmware update required). |

### Responses (Arduino to Python)

| Response | When |
|----------|------|
| `READY` | On startup, signals handshake complete |
| `System OFF. Position saved.` | After command `0` |
| `Pumps ON` | After command `123` |
| `Direction switched.` | After command `321` |
| `LOG: Position: X, FWD: Y...` | After command `456` |
| `Flow rate changed to X uL/min` | After a numeric flow rate command |

---

## Troubleshooting

**App won't start / ModuleNotFoundError**
- Make sure you've installed dependencies: `pip install PyQt5 pyserial`
- Run from inside the `Python code/` directory so relative imports work.

**"No device found" on connect**
- Check that the Arduino is plugged in via USB.
- On macOS, verify the device appears under `/dev/cu.*` (run `ls /dev/cu.*` in terminal).
- Try entering the device path manually (e.g. `/dev/cu.usbmodem1101`).

**Connect button turns red**
- The auto-detection couldn't find a matching device. Try manual serial entry or check USB connection.

**Pump doesn't respond to FLOW commands**
- The Arduino firmware (`pump_JS_07222025.ino`) does not yet handle `FLOWA`/`FLOWB`/`FLOWC`/`FLOWD` commands. Numeric flow rate changes and on/off/direction work. The firmware needs to be updated to parse the new comma-separated flow commands.

**Pause/Resume not working**
- These buttons only work when a text file schedule is running. For manual control, use the On/Off button directly.

**File displays "no valid commands found"**
- Check that the file uses the correct format: `SERIAL*********COMMAND#########DELAY` with `%%%%%%%%%` separators.

**Multiple pumps - wrong pump receives commands**
- Use the pump dropdown to select which pump you're controlling manually.
- In text files, make sure each command line uses the correct serial number for the target pump.
