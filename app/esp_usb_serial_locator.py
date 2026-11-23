"""Find the physical Espressif USB Serial/JTAG device after macOS port renumbering.

Never guess or take over a modem belonging to another maker. Multiple matching
boards are ambiguous; the physical session owner must not choose one blindly.
"""
from __future__ import annotations
from typing import Iterable

ESPRESSIF_VID = 0x303A
ESP32_S3_USB_SERIAL_JTAG_PID = 0x1001

class ESPSerialPortUnavailable(RuntimeError):
    pass

def select_esp32_port(ports: Iterable[object]) -> str:
    matches = []
    for port in ports:
        name = getattr(port, "device", None)
        vid = getattr(port, "vid", None)
        pid = getattr(port, "pid", None)
        if (isinstance(name, str) and name.startswith("/dev/cu.usbmodem")
                and vid == ESPRESSIF_VID and pid == ESP32_S3_USB_SERIAL_JTAG_PID):
            matches.append(name)
    matches = sorted(set(matches))
    if len(matches) != 1:
        reason = ("not_found" if not matches else "multiple_esp32_s3_devices")
        raise ESPSerialPortUnavailable("ESP32_USB_SERIAL_JTAG_" + reason)
    return matches[0]

def resolve_esp32_port() -> str:
    from serial.tools import list_ports
    return select_esp32_port(list_ports.comports())
