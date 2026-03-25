---
layout: default
---

<p align="center">
  <img src="img/hero_figure.png" alt="Platform Overview - GUI, Pump Hardware, Flow Behaviors" width="900">
</p>

[View on GitHub](https://github.com/SamOliveiraLab/DIY_DSCPM){: .btn }

---

## Demos

<!-- Replace VIDEO_ID_GUI, VIDEO_ID_FIRMWARE, VIDEO_ID_HARDWARE with your actual YouTube video IDs -->
<table align="center">
  <tr>
    <td align="center">
      <iframe width="320" height="180" src="https://www.youtube.com/embed/VIDEO_ID_GUI" frameborder="0" allowfullscreen></iframe>
      <br><b>GUI Demo</b>
    </td>
    <td align="center">
      <iframe width="320" height="180" src="https://www.youtube.com/embed/VIDEO_ID_FIRMWARE" frameborder="0" allowfullscreen></iframe>
      <br><b>Firmware Demo</b>
    </td>
    <td align="center">
      <iframe width="320" height="180" src="https://www.youtube.com/embed/VIDEO_ID_HARDWARE" frameborder="0" allowfullscreen></iframe>
      <br><b>Hardware Demo</b>
    </td>
  </tr>
</table>

---

## Quick Links

| Page | Description |
|------|-------------|
| [Setup & Installation](setup.html) | Requirements, dependencies, and how to run |
| [GUI User Guide](guide.html) | Full walkthrough of every feature |
| [Flow Behaviors](flow.html) | Constant, Pulse, Oscillation, and Pulse of Oscillation modes |
| [Experiment Builder](experiment.html) | Creating and running scheduled experiments |
| [Arduino Protocol](protocol.html) | Command format between Python and the microcontroller |
| [Troubleshooting](troubleshooting.html) | Common issues and fixes |

---

## Project Structure

```
DIY_DSCPM/
├── Arduino_code/
│   └── pump_JS_07222025.ino    # Arduino firmware
├── Python code/
│   ├── GUI.py                  # Entry point
│   ├── pump_app.py             # Main window and logic
│   ├── arduino_cmds.py         # Serial communication
│   ├── autoport.py             # USB auto-detection
│   └── pump_render.png         # Pump image
├── dist/
│   ├── PumpGUI.app             # Standalone macOS app
│   └── PumpGUI                 # Standalone CLI executable
└── README.md
```

---

*Developed at the [Oliveira Lab](https://github.com/SamOliveiraLab), North Carolina A&T State University.*
