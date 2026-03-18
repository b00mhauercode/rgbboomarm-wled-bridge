"""
MANKA-LED-STRIP test script
Sends a color sequence to verify the strip responds correctly.
Run this after setting your DEVICE_MAC and ROLLING below.
"""
import asyncio
from bleak import BleakClient
from manka_proto import DEVICE_MAC, ROLLING, FFF3_UUID, FFF4_UUID, pkt_color, pkt_off

responses = []
def notify_handler(sender, data):
    print(f"  << {data.hex()}")
    responses.append(data)

async def w(client, label, data, wait=3.0):
    print(f"[{label}]  {data.hex()}")
    await client.write_gatt_char(FFF3_UUID, data, response=False)
    await asyncio.sleep(wait)

async def main():
    async with BleakClient(DEVICE_MAC) as client:
        print(f"Connected\n")
        await client.start_notify(FFF4_UUID, notify_handler)
        await asyncio.sleep(1.0)

        # Replicate exact app sequence: RED with lum=0 first, then lum=100
        print("--- Exact app sequence ---")
        await w(client, "RED lum=0   (app sends this first)", pkt_color(r=255, g=0, b=0, lum=0))
        await w(client, "RED lum=100 (then bumps brightness)", pkt_color(r=255, g=0, b=0, lum=100))

        await w(client, "GREEN lum=100", pkt_color(r=0,   g=255, b=0,   lum=100))
        await w(client, "BLUE  lum=100", pkt_color(r=0,   g=0,   b=255, lum=100))
        await w(client, "WHITE lum=100", pkt_color(r=255, g=255, b=255, lum=100))
        await w(client, "WHITE lum=50 ", pkt_color(r=255, g=255, b=255, lum=50))
        await w(client, "OFF",           pkt_off())

asyncio.run(main())
