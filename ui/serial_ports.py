"""List the serial ports on this computer (used by the port dropdown and the status bar)."""

from __future__ import annotations


def list_serial_ports() -> list[str]:
    """Names of the serial ports on this computer, e.g. ['COM3', 'COM4']."""
    try:
        from PySide6.QtSerialPort import QSerialPortInfo
    except ImportError:  # some minimal PySide6 builds leave QtSerialPort out
        return []
    return sorted(info.portName() for info in QSerialPortInfo.availablePorts())
