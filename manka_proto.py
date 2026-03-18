"""
Shared MANKA-LED-STRIP protocol constants and packet builders.
All scripts in this repository import from here.
"""
try:
    from config_local import DEVICE_MAC, ROLLING
except ImportError:
    from config import DEVICE_MAC, ROLLING
ROLLING = bytes.fromhex(ROLLING)

FFF3_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
FFF4_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"


def pkt_color(r, g, b, lum=100):
    return bytes([0xFB, 0xFB, 0xFB, 0x0A]) + ROLLING + bytes([
        0x00, 0x00,   # scene_id
        0x22,         # solid color mode
        lum & 0xFF,   # brightness 0-100
        0x00, 0x00,   # speed
        0x00, 0x00,   # defcol, multicolor
        r, g, b,
        0x00,
    ])


def pkt_off():
    return bytes([0xFB, 0xFB, 0xFB, 0x0A]) + ROLLING + bytes(12)
