import serial.tools.list_ports
from datetime import date
import os
import arduino_cmds

#SEARCHING FOR CORRECT DEVICE SERIAL NUMBER
your_serial = "054433A493735191B7D8"
#your_serial = ""
DEVICES = [p.serial_number for p in serial.tools.list_ports.comports() if p.serial_number==your_serial] # lab - 2423632373035190C2B1  mine - 054433A493735191B7D8

def connect(SERIAL=your_serial):
    """
    Connect to a pump controller over USB serial.

    Accepts either:
    - SERIAL: a USB serial number (matches `list_ports.comports().serial_number`)
    - SERIAL: a device path like `/dev/cu.usbmodem1101` or `/dev/cu.usbserial-XYZ`

    If SERIAL doesn't match anything, falls back to a best-effort auto-pick of a
    likely USB serial port (prefers `cu.usbmodem*`, then `cu.usbserial*`/`wchusbserial*`).
    """
    serial_arg = "" if SERIAL is None else str(SERIAL).strip()
    print("Today's date:", date.today())
    print("OPERATING SYSTEM:", os.name)

    ports = list(serial.tools.list_ports.comports())

    # 1) Direct device path match
    if serial_arg.startswith("/dev/"):
        for p in ports:
            if p.device == serial_arg:
                print("DEVICE FOUND:", p.device)
                ac = arduino_cmds.PumpFluidics()
                ac.comPort = p.device
                ac.connect()
                print("connected")
                # Store under both device path and USB serial number (if present)
                connected_device = {p.device: ac}
                if p.serial_number:
                    connected_device[p.serial_number] = ac
                return ac, connected_device

    # 2) USB serial-number match
    if serial_arg:
        for p in ports:
            if p.serial_number and p.serial_number == serial_arg:
                print("DEVICE FOUND:", p.device)
                ac = arduino_cmds.PumpFluidics()
                ac.comPort = p.device
                ac.connect()
                print("connected")
                connected_device = {p.device: ac, p.serial_number: ac}
                return ac, connected_device

    # 3) Best-effort auto-pick
    def _score(device: str) -> int:
        d = device.lower()
        if "usbmodem" in d:
            return 0
        if "wchusbserial" in d:
            return 1
        if "usbserial" in d:
            return 2
        if d.startswith("/dev/cu."):
            return 10
        return 100

    candidates = sorted(ports, key=lambda p: (_score(p.device), p.device))
    for p in candidates:
        # Ignore bluetooth pseudo-ports
        if "bluetooth" in p.device.lower():
            continue
        if p.device.startswith("/dev/cu."):
            print("AUTO-SELECTED DEVICE:", p.device)
            ac = arduino_cmds.PumpFluidics()
            ac.comPort = p.device
            ac.connect()
            print("connected")
            connected_device = {p.device: ac}
            if p.serial_number:
                connected_device[p.serial_number] = ac
            return ac, connected_device

    raise Exception("No device found")

def connect_multiple(serial_list):
    # Get available serial ports
    available_ports = list(serial.tools.list_ports.comports())
    connected_devices = {}

    print("Today's date:", date.today())
    print("OPERATING SYSTEM:", os.name)

    for serial_number in serial_list:
        matched_ports = [p for p in available_ports if p.serial_number == str(serial_number)]

        if not matched_ports:
            print(f"Device with serial {serial_number} not found.")
            continue

        # Only take the first matching port (should be one)
        port = matched_ports[0]
        print("DEVICE FOUND:", port.device)

        ac = arduino_cmds.PumpFluidics()
        ac.comPort = port.device
        ac.connect()
        print(f'Connected to device {serial_number} on port {port.device}')
        # Store under both the requested serial number and the port path,
        # so scripts can reference either.
        connected_devices[str(serial_number)] = ac
        connected_devices[port.device] = ac

    if not connected_devices:
        raise Exception("No devices were connected.")

    return connected_devices
