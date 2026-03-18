"""
MANKA-LED-STRIP BLE query / debug tool
Tests query commands (A6, B0) and logs all FFF4 notifications.
This was used during reverse engineering to probe device responses.

NOTE: These query commands did not produce responses from the device.
Included for reference / future investigation.
"""
import asyncio
from bleak import BleakClient
from manka_proto import DEVICE_MAC, ROLLING, FFF3_UUID, FFF4_UUID

def pad20(b):
    assert len(b) <= 20
    return b + bytes(20 - len(b))

def pkt_query_state():
    # CMD_GET_OPEN_LIGHT_STATU_REQ (A6)
    # Case 18: rolling_code(4) + group_id d("0000")=2 bytes
    return pad20(bytes([0xFB, 0xFB, 0xFB, 0xA6]) + ROLLING + bytes([0x00, 0x00]))

def pkt_query_b0():
    # CMD_GET_COLOUR_LIGHT_REQ (B0) - case 24: just rolling_code
    return pad20(bytes([0xFB, 0xFB, 0xFB, 0xB0]) + ROLLING)

responses = []
def notify_handler(sender, data):
    msg = f"  << FFF4: {data.hex()}"
    print(msg)
    responses.append(msg)

async def main():
    async with BleakClient(DEVICE_MAC) as client:
        print(f"Connected. MTU={client.mtu_size}")
        await client.start_notify(FFF4_UUID, notify_handler)
        print("Subscribed FFF4. Waiting 2s...\n")
        await asyncio.sleep(2.0)

        # Try reading FFF4 directly
        try:
            val = await client.read_gatt_char(FFF4_UUID)
            print(f"[FFF4 direct read] {val.hex()}")
        except Exception as e:
            print(f"[FFF4 direct read] ERR: {e}")

        async def send(label, data):
            print(f"\n[{label}]  {data.hex()}")
            try:
                await client.write_gatt_char(FFF3_UUID, data, response=False)
                print("  >> sent, waiting 2s for response...")
            except Exception as e:
                print(f"  >> ERR: {e}")
            await asyncio.sleep(2.0)
            print(f"  FFF4 count so far: {len(responses)}")

        await send("A6 query state", pkt_query_state())
        await send("B0 query color", pkt_query_b0())

        # Try B3 RED with rolling=00000000
        pkt_zero_roll = pad20(bytes([
            0xFB, 0xFB, 0xFB, 0xB3,
            0x00, 0x00, 0x00, 0x00,  # zero rolling
            0x06, 0x01, 0x01, 0x00,
            0xFF, 0x00, 0x00, 0x64, 0x01,
        ]))
        await send("B3 RED zero-rolling", pkt_zero_roll)

        # Try B3 RED with FFFFFFFF rolling
        pkt_ff_roll = pad20(bytes([
            0xFB, 0xFB, 0xFB, 0xB3,
            0xFF, 0xFF, 0xFF, 0xFF,  # FFFFFFFF rolling
            0x06, 0x01, 0x01, 0x00,
            0xFF, 0x00, 0x00, 0x64, 0x01,
        ]))
        await send("B3 RED FFFFFFFF-rolling", pkt_ff_roll)

        print(f"\n--- Total FFF4 notifications: {len(responses)} ---")
        for r in responses:
            print(r)

asyncio.run(main())
