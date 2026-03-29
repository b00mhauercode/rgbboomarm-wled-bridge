"""
MANKA WLED Bridge
Presents the MANKA LED strip as a WLED device so SignalRGB's built-in
WLED integration can discover and stream colors to it.

Usage:
  Run as Administrator:   python manka_wled_bridge.py
  (Port 80 requires admin on Windows)

In SignalRGB:
  Home -> Lighting Services -> WLED -> "Discover WLED device by IP" -> 127.0.0.1
  Press Enter, wait a moment — "MANKA LED Strip" will appear and you can link it.
"""
import asyncio
import json
import os
import socketserver
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from bleak import BleakClient
from manka_proto import DEVICE_MAC, ROLLING, FFF3_UUID, FFF4_UUID, pkt_color, pkt_off

try:
    from config_local import WLED_MAC
except ImportError:
    from config import WLED_MAC

HTTP_PORT       = 80
UDP_PORT        = 21324
SEND_INTERVAL   = 0.05   # max 20 Hz BLE writes
RECONNECT_DELAY = 5.0
EASE_FACTOR     = 0.18   # fraction of remaining distance to close per frame (lower = slower)
SNAP_THRESHOLD  = 1.5    # snap to target when this close (avoids infinite crawl)
SCENE_CUT_DELTA = 220    # if any channel jumps more than this, snap instantly instead of fading
                         # set to 255 to disable scene-cut snapping entirely


# ── Shared color/brightness state ──────────────────────────────────────────────

_lock       = threading.Lock()
_pending    = None    # (r, g, b) or None
_global_lum = 100     # hardware brightness 0-100, driven by SignalRGB

def set_color(r, g, b):
    global _pending
    with _lock:
        _pending = (r, g, b)

def set_brightness(lum_0_100):
    global _global_lum
    with _lock:
        _global_lum = max(0, min(100, lum_0_100))


# ── WLED JSON responses ────────────────────────────────────────────────────────

WLED_INFO = {
    "ver": "0.14.0",
    "vid": 2310130,
    "leds": {
        "count": 1,
        "pwr": 0,
        "fps": 30,
        "maxpwr": 5,
        "maxseg": 32,
        "seglc": [1],
        "lc": 1,
        "rgbw": False,
        "wv": 0,
        "cct": 0,
    },
    "str": False,
    "name": "MANKA LED Strip",
    "udpport": UDP_PORT,
    "live": False,
    "lm": "",
    "lip": "",
    "ws": 0,
    "fxcount": 118,
    "palcount": 71,
    "cpalcount": 0,
    "wifi": {"bssid": "00:00:00:00:00:00", "rssi": -50, "signal": 100, "channel": 1},
    "fs": {"u": 0, "t": 0, "pj": 0},
    "ndc": 0,
    "arch": "esp32",
    "core": "v3.3.6",
    "lwip": 2,
    "freeheap": 100000,
    "uptime": 1000,
    "opt": 131,
    "brand": "WLED",      # ← SignalRGB checks this field
    "product": "FOSS",
    "mac": WLED_MAC,
    "ip": "127.0.0.1",
}

WLED_STATE = {
    "on": True,
    "bri": 255,
    "transition": 7,
    "ps": -1,
    "pl": -1,
    "nl": {"on": False, "dur": 60, "mode": 1, "tbri": 0, "rem": -1},
    "udpn": {"send": False, "recv": False, "sgrp": 0, "rgrp": 0},
    "lor": 0,
    "mainseg": 0,
    "seg": [{
        "id": 0, "start": 0, "stop": 1, "len": 1,
        "grp": 1, "spc": 0, "of": 0, "on": True, "frz": False,
        "bri": 255, "cct": 127, "set": 0,
        "col": [[255, 255, 255, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "fx": 0, "sx": 128, "ix": 128, "pal": 0,
        "c1": 128, "c2": 128, "c3": 16,
        "sel": True, "rev": False, "mi": False,
        "o1": False, "o2": False, "o3": False,
        "si": 0, "m12": 0,
    }],
}


# ── HTTP handler (port 80) ─────────────────────────────────────────────────────

class WLEDHttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path in ("/json/info", "/json"):
            if path == "/json":
                body = json.dumps({"state": WLED_STATE, "info": WLED_INFO}).encode()
            else:
                body = json.dumps(WLED_INFO).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/json/state":
            length = int(self.headers.get("Content-Length", 0))
            if length > 4096:          # reject oversized bodies
                self.send_response(413)
                self.end_headers()
                return
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                # Brightness: SignalRGB sends bri 0-255; convert to 0-100 for hardware
                if "bri" in data:
                    lum = round(data["bri"] / 255 * 100)
                    set_brightness(lum)
                    WLED_STATE["bri"] = data["bri"]
                if data.get("on") is False:
                    set_color(0, 0, 0)
            except Exception as e:
                print(f"  HTTP POST /json/state parse error: {e}")
            resp = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        print(f"  HTTP {args[0]} {args[1]}")


# ── UDP handler (port 21324) ───────────────────────────────────────────────────

class WLEDUdpHandler(socketserver.BaseRequestHandler):
    """
    WLED DRGB streaming packet: [0x04][timeout][hiIdx][loIdx][R][G][B]...
    SignalRGB sends one packet per frame with all LED RGB values inline.
    """
    def handle(self):
        data = self.request[0]
        if len(data) < 7:
            return
        protocol = data[0]
        if protocol == 0x04:            # DRGB — 3 bytes per pixel after 4-byte header
            r, g, b = data[4], data[5], data[6]
            set_color(r, g, b)
        elif protocol == 0x01:          # WARLS — [proto][timeout][idx][R][G][B]...
            i = 2
            while i + 3 <= len(data):
                if data[i] == 0:
                    set_color(data[i+1], data[i+2], data[i+3])
                    break               # single-zone device — only pixel 0 matters
                i += 4


# ── BLE loop ───────────────────────────────────────────────────────────────────

async def ble_loop():
    last_sent  = None
    last_lum   = None
    last_time  = 0.0
    smooth_r   = 0.0
    smooth_g   = 0.0
    smooth_b   = 0.0

    print(f"Connecting to BLE {DEVICE_MAC}...")
    while True:
        try:
            async with BleakClient(DEVICE_MAC) as client:
                print("BLE connected!")
                await client.start_notify(FFF4_UUID, lambda s, d: None)
                await asyncio.sleep(0.5)

                while client.is_connected:
                    now = asyncio.get_running_loop().time()
                    with _lock:
                        color = _pending
                        lum   = _global_lum

                    if color is not None and (now - last_time) >= SEND_INTERVAL:
                        tr, tg, tb = color
                        # scene-cut: snap instantly on large jumps
                        if max(abs(tr - smooth_r), abs(tg - smooth_g), abs(tb - smooth_b)) > SCENE_CUT_DELTA:
                            smooth_r, smooth_g, smooth_b = float(tr), float(tg), float(tb)
                        else:
                            def _ease(cur, tgt):
                                diff = tgt - cur
                                if abs(diff) <= SNAP_THRESHOLD:
                                    return float(tgt)
                                return cur + diff * EASE_FACTOR
                            smooth_r = _ease(smooth_r, tr)
                            smooth_g = _ease(smooth_g, tg)
                            smooth_b = _ease(smooth_b, tb)
                        r, g, b = round(smooth_r), round(smooth_g), round(smooth_b)
                        if (r, g, b) == last_sent and lum == last_lum:
                            await asyncio.sleep(0.02)
                            continue
                        pkt = pkt_off() if (r == 0 and g == 0 and b == 0) \
                              else pkt_color(r, g, b, lum)
                        try:
                            await client.write_gatt_char(FFF3_UUID, pkt, response=False)
                            last_sent = color
                            last_lum  = lum
                            last_time = now
                            print(f"  BLE -> rgb({r:3d},{g:3d},{b:3d}) lum={lum}%")
                        except Exception as e:
                            print(f"  BLE write error: {e}")
                            break

                    await asyncio.sleep(0.02)

        except Exception as e:
            print(f"BLE error: {e}")
        print(f"Reconnecting in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # UDP server — no admin needed on Windows
    # Bound to 127.0.0.1 so only SignalRGB on this machine can send color packets
    udp_server = socketserver.UDPServer(("127.0.0.1", UDP_PORT), WLEDUdpHandler)
    threading.Thread(target=udp_server.serve_forever, daemon=True).start()
    print(f"WLED UDP streaming on 127.0.0.1:{UDP_PORT}")

    # HTTP server — needs admin on Windows for port 80
    # Bound to 127.0.0.1 so only SignalRGB on this machine can discover it
    try:
        http_server = HTTPServer(("127.0.0.1", HTTP_PORT), WLEDHttpHandler)
        threading.Thread(target=http_server.serve_forever, daemon=True).start()
        print(f"WLED HTTP API on :{HTTP_PORT}")
    except PermissionError:
        user = os.environ.get("USERNAME", "Everyone")
        print(f"\nERROR: Port 80 requires Administrator privileges.")
        print(f"  Option A: Right-click your terminal -> 'Run as administrator'")
        print(f"  Option B (one-time): run this in an admin prompt, then re-run normally:")
        print(f"    netsh http add urlacl url=http://+:80/ user={user}")
        sys.exit(1)

    print()
    print("In SignalRGB: Lighting Services -> WLED -> enter IP: 127.0.0.1")
    print("Ctrl+C to quit\n")

    try:
        asyncio.run(ble_loop())
    except KeyboardInterrupt:
        print("\nShutting down.")
        udp_server.shutdown()
        http_server.shutdown()


if __name__ == "__main__":
    main()
