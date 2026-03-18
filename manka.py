"""
MANKA-LED-STRIP BLE controller
Device: SUNMON RGB Boom Arm (MANKA-LED-STRIP)
MAC:    XX:XX:XX:XX:XX:XX  ← replace with your device MAC

Usage:
  python manka.py on
  python manka.py off
  python manka.py red
  python manka.py green
  python manka.py blue
  python manka.py white
  python manka.py rgb 255 0 128
  python manka.py bright 75        # 0-100
  python manka.py rgb 255 0 0 50   # RGB + brightness

Scene/effect exploration (CMD=0x0A, vary scene_id and mode byte):
  python manka.py scene 1          # try scene_id=1 (solid mode)
  python manka.py scene 2          # try scene_id=2
  python manka.py effect 0x01      # try mode byte 0x01 (decimal or 0x hex)
  python manka.py effect 34        # 0x22 = solid color (confirmed working)
"""
import asyncio
import sys
from bleak import BleakClient
from manka_proto import DEVICE_MAC, ROLLING, FFF3_UUID, FFF4_UUID, pkt_color, pkt_off

# Default on/bright state — each invocation is independent (no persistence between runs)
_state = {"r": 255, "g": 255, "b": 255, "lum": 100}

def pkt_scene(scene_id, mode_byte=0x22, r=255, g=255, b=255, lum=100):
    """
    Exploration packet — vary scene_id (2 bytes) and mode_byte to probe
    whether the device has built-in animations.
    CMD=0x0A confirmed working.  mode 0x22 = solid color.
    """
    scene_hi = (scene_id >> 8) & 0xFF
    scene_lo = scene_id & 0xFF
    return bytes([0xFB, 0xFB, 0xFB, 0x0A]) + ROLLING + bytes([
        scene_hi, scene_lo,  # scene_id (2 bytes)
        mode_byte,           # mode/effect byte
        lum & 0xFF,          # brightness 0-100
        0x00, 0x00,          # speed
        0x00, 0x00,          # defcol, multicolor
        r, g, b,
        0x00,
    ])

async def send(pkt):
    async with BleakClient(DEVICE_MAC) as client:
        await client.start_notify(FFF4_UUID, lambda s, d: None)
        await asyncio.sleep(0.5)
        await client.write_gatt_char(FFF3_UUID, pkt, response=False)
        await asyncio.sleep(0.5)

COLORS = {
    "red":     (255, 0,   0),
    "green":   (0,   255, 0),
    "blue":    (0,   0,   255),
    "white":   (255, 255, 255),
    "warm":    (255, 180, 80),
    "cyan":    (0,   255, 255),
    "magenta": (255, 0,   255),
    "yellow":  (255, 220, 0),
    "orange":  (255, 80,  0),
    "purple":  (128, 0,   255),
}

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0].lower()

    if cmd == "off":
        print("Turning off...")
        asyncio.run(send(pkt_off()))

    elif cmd == "on":
        r, g, b = _state["r"], _state["g"], _state["b"]
        lum = _state["lum"]
        print(f"On: rgb({r},{g},{b}) lum={lum}%")
        asyncio.run(send(pkt_color(r, g, b, lum)))

    elif cmd in COLORS:
        r, g, b = COLORS[cmd]
        try:
            lum = int(args[1]) if len(args) > 1 else 100
        except ValueError:
            print(f"Invalid brightness '{args[1]}' — must be 0-100")
            return
        lum = max(0, min(100, lum))
        print(f"{cmd}: rgb({r},{g},{b}) lum={lum}%")
        asyncio.run(send(pkt_color(r, g, b, lum)))

    elif cmd == "rgb":
        if len(args) < 4:
            print("Usage: python manka.py rgb <R> <G> <B> [brightness]")
            return
        try:
            r, g, b = int(args[1]), int(args[2]), int(args[3])
            lum = int(args[4]) if len(args) > 4 else 100
        except ValueError:
            print("Invalid value — R/G/B must be 0-255 integers, brightness 0-100")
            return
        r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        lum = max(0, min(100, lum))
        print(f"rgb({r},{g},{b}) lum={lum}%")
        asyncio.run(send(pkt_color(r, g, b, lum)))

    elif cmd == "bright":
        if len(args) < 2:
            print("Usage: python manka.py bright <0-100>")
            return
        try:
            lum = int(args[1])
        except ValueError:
            print(f"Invalid brightness '{args[1]}' — must be 0-100")
            return
        lum = max(0, min(100, lum))
        r, g, b = _state["r"], _state["g"], _state["b"]
        print(f"Brightness {lum}%")
        asyncio.run(send(pkt_color(r, g, b, lum)))

    elif cmd == "scene":
        # Probe built-in scene animations by varying scene_id
        if len(args) < 2:
            print("Usage: python manka.py scene <scene_id>  (try 0-255)")
            return
        try:
            scene_id = int(args[1], 0)   # accepts decimal or 0x hex
        except ValueError:
            print(f"Invalid scene_id '{args[1]}' — use decimal (1) or hex (0x01)")
            return
        lum = 100
        pkt = pkt_scene(scene_id, mode_byte=0x22, lum=lum)
        print(f"Scene probe: scene_id={scene_id} (0x{scene_id:04x})  mode=0x22")
        print(f"  raw packet: {pkt.hex()}")
        asyncio.run(send(pkt))

    elif cmd == "effect":
        # Probe built-in effects by varying the mode byte
        if len(args) < 2:
            print("Usage: python manka.py effect <mode_byte>  (try 0-255; 0x22=solid)")
            return
        try:
            mode_byte = int(args[1], 0)   # accepts decimal or 0x hex
        except ValueError:
            print(f"Invalid mode_byte '{args[1]}' — use decimal (34) or hex (0x22)")
            return
        mode_byte = max(0, min(255, mode_byte))
        pkt = pkt_scene(scene_id=0, mode_byte=mode_byte)
        print(f"Effect probe: mode_byte=0x{mode_byte:02x} ({mode_byte})")
        print(f"  raw packet: {pkt.hex()}")
        asyncio.run(send(pkt))

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

if __name__ == "__main__":
    main()
