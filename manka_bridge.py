"""
MANKA-LED-STRIP SignalRGB Bridge
Listens for HTTP color commands from the SignalRGB plugin and forwards them
to the MANKA BLE strip.

NOTE: manka_wled_bridge.py is the preferred integration for SignalRGB.
This file is an alternative that uses a simpler custom HTTP bridge on port 12345
instead of emulating a WLED device. Use this if you have issues with port 80.

Usage:
  python manka_bridge.py

The SignalRGB plugin sends GET requests to:
  http://127.0.0.1:12345/?r=255&g=0&b=128

Keep this running in the background while SignalRGB is active.
"""
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from bleak import BleakClient
from manka_proto import DEVICE_MAC, ROLLING, FFF3_UUID, FFF4_UUID, pkt_color, pkt_off

PORT = 12345
SEND_INTERVAL = 0.05   # max 20Hz BLE writes
RECONNECT_DELAY = 5.0


# --- Shared state (thread-safe) ---
_lock = threading.Lock()
_pending = None   # (r, g, b) or None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _pending
        try:
            params = parse_qs(urlparse(self.path).query)
            r = max(0, min(255, int(params["r"][0])))
            g = max(0, min(255, int(params["g"][0])))
            b = max(0, min(255, int(params["b"][0])))
            with _lock:
                _pending = (r, g, b)
            self.send_response(200)
        except (KeyError, ValueError, IndexError):
            self.send_response(400)
        self.end_headers()

    def log_message(self, *args):
        pass  # suppress access logs


async def ble_loop():
    last_sent = None
    last_time = 0.0

    print(f"Connecting to {DEVICE_MAC}...")

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

                    if color is not None and color != last_sent and (now - last_time) >= SEND_INTERVAL:
                        r, g, b = color
                        pkt = pkt_off() if (r == 0 and g == 0 and b == 0) else pkt_color(r, g, b)
                        try:
                            await client.write_gatt_char(FFF3_UUID, pkt, response=False)
                            last_sent = color
                            last_time = now
                            print(f"  -> rgb({r:3d},{g:3d},{b:3d})")
                        except Exception as e:
                            print(f"  write error: {e}")
                            break

                    await asyncio.sleep(0.02)  # poll at 50Hz

        except Exception as e:
            print(f"BLE error: {e}")

        print(f"Reconnecting in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"HTTP bridge listening on 127.0.0.1:{PORT}")
    print("Ctrl+C to quit\n")

    try:
        asyncio.run(ble_loop())
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
