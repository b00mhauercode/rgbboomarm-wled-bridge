# MANKA-LED-STRIP BLE Reverse Engineering

> Full Python controller, SignalRGB integration, and technical protocol documentation for the **SUNMON RGB Boom Arm** LED strip (sold under the Manka brand on Amazon/AliExpress).

---

## Table of Contents

1. [Device Identification](#device-identification)
2. [The Reverse Engineering Journey](#the-reverse-engineering-journey)
3. [Protocol Specification](#protocol-specification)
4. [Finding Your Rolling Code](#finding-your-rolling-code)
5. [Installation](#installation)
6. [CLI Usage](#cli-usage)
7. [SignalRGB Integration](#signalrgb-integration)
8. [Mac Mini / Home Server](#mac-mini--home-server)
9. [Architecture](#architecture)
10. [Files in This Repo](#files-in-this-repo)
11. [Future Work](#future-work)
12. [Legal](#legal)

---

## Device Identification

| Field | Value |
|---|---|
| Brand / App | Manka / HomeLinking (`com.hle.lhzm`) |
| Product | SUNMON RGB Boom Arm mic stand LED strip |
| Model | SC1TW3CQ21NB |
| Firmware | 1.0.25 |
| BLE Advertised Name | `MANKA-LED-STRIP` |
| Power | 5V USB |

### BLE Services

| Service UUID | Characteristic | Properties | Purpose |
|---|---|---|---|
| `FFF0` | `FFF3` | Write, Write-No-Response | **Command channel** — send all control packets here |
| `FFF0` | `FFF4` | Notify, Read | Response/notification channel — subscribe before writing |
| `5833FF01` | `5833FF02` | Write | OTA firmware update — **ignore** |

---

## The Reverse Engineering Journey

### What We Tried First (And Wasted Time On)

The HomeLinking app requires an **AWS cloud account login** to pair the device. This immediately complicated things — there was no simple local pairing we could observe.

**Attempt 1 — APK decompilation (JADX)**

We decompiled the HomeLinking APK and found two candidate transports:

1. **FBFBFB protocol** — `q1/c.java` + `r1/b.java` → uses FFF0/FFF3/FFF4 with a `0xFB 0xFB 0xFB` magic header. Commands found: `B3` (color), `A0` (power), `B5` (query), `A6` (state query).

2. **WiCom protocol** — `j1/q.java` → uses a 28-byte format: `[wid 4B][dst 6B][src 6B][opCode+seq 4B][payload]`

We spent significant time implementing both. The FBFBFB/B3 packet format from the decompile looked correct — it had RGB, brightness, scene ID fields — but **nothing happened**. No light change, no FFF4 response. We tried:

- Multiple rolling code derivations (MAC-based, zero, `0xFFFFFFFF`)
- Both B3 and A0 command bytes
- The full WiCom 28-byte format
- Scanning the APK for any encryption or obfuscation

None of it worked.

**Why the brute force approach failed:**

The APK had multiple code paths. We were implementing the right *structure* but the wrong *command byte*, and the rolling code we were deriving from the MAC address was completely wrong — the actual rolling code comes from the cloud account session, not the device MAC. Without a real packet capture, we were guessing.

### The Breakthrough — Android HCI Snoop Log

The turning point was capturing a Bluetooth HCI snoop log directly from an Android phone while the HomeLinking app was actively controlling the strip.

**Process:**
1. Enable Developer Options on Android → enable **"Bluetooth HCI snoop log"**
2. Open HomeLinking, pair and control the strip (change colors, turn on/off)
3. Pull the log via ADB:
   ```bash
   # Samsung devices store the log inside a bugreport zip
   adb bugreport bugreport.zip
   # Extract: FS/data/log/bt/btsnoop_hci.log
   ```
4. Parse with `parse_btsnoop.py` to extract ATT Write packets

The snoop log immediately revealed the **actual packets** the app was sending. Everything became clear within minutes of having the real capture.

### What the Snoop Log Revealed

The working command byte is **`0x0A`** — not `B3` as found in the APK decompile.

The rolling code is **not MAC-derived**. It's the ASCII bytes of the last 4 characters of the HomeLinking account's `userCode` field. In our case the userCode ended in `"ABCD"` → `bytes.fromhex("41424344")`.

> **Lesson:** For any BLE device tied to a cloud app, skip the APK decompile and go straight to an HCI snoop log. The decompile is useful for understanding structure, but the live packet capture gives you the exact bytes immediately.

---

## Protocol Specification

### Packet Format

All control packets are **20 bytes**, sent as ATT Write-No-Response to characteristic `FFF3`.

```
Offset  Size  Field           Value / Notes
──────  ────  ─────────────   ────────────────────────────────────────────
0       3     Magic header    0xFB 0xFB 0xFB
3       1     Command         0x0A = set color/state
4       4     Rolling code    ASCII bytes of last 4 chars of userCode (account-specific)
8       2     Scene ID        0x00 0x00 (solid color scene)
10      1     Mode byte       0x22 = solid color ON | 0x00 = OFF
11      1     Brightness      0–100 decimal
12      2     Speed           0x00 0x00
14      2     Reserved        0x00 0x00
16      1     Red             0–255
17      1     Green           0–255
18      1     Blue            0–255
19      1     Padding         0x00
```

### Color Command

```python
def pkt_color(r, g, b, lum=100):
    return bytes([0xFB, 0xFB, 0xFB, 0x0A]) + ROLLING + bytes([
        0x00, 0x00,   # scene_id
        0x22,         # solid color mode (ON)
        lum & 0xFF,   # brightness 0–100
        0x00, 0x00,   # speed
        0x00, 0x00,   # reserved
        r, g, b,
        0x00,
    ])
```

### Off Command

```python
def pkt_off():
    return bytes([0xFB, 0xFB, 0xFB, 0x0A]) + ROLLING + bytes(12)
```

The off packet is identical in structure but with all trailing bytes zeroed — mode byte `0x00` means off.

### Sending a Packet

Always subscribe to FFF4 notifications before writing to FFF3. The device expects this handshake.

```python
async with BleakClient(DEVICE_MAC) as client:
    await client.start_notify(FFF4_UUID, lambda sender, data: None)
    await asyncio.sleep(0.5)
    await client.write_gatt_char(FFF3_UUID, packet, response=False)
```

---

## Finding Your Rolling Code

> ⚠️ **The rolling code (`ROLLING`) in this repo is specific to one HomeLinking account.** You must find your own before the commands will work.

The rolling code is 4 bytes — the ASCII encoding of the last 4 characters of your HomeLinking account's `userCode`.

### Method 1: Android HCI Snoop Log ✅ Proven

This is the method we used and know works. You need an Android phone with the HomeLinking app installed and your device already paired.

**Step 1 — Enable HCI logging on Android**
1. Go to **Settings → About Phone** → tap Build Number 7 times to enable Developer Options
2. Go to **Settings → Developer Options** → enable **"Bluetooth HCI snoop log"**
3. Toggle Bluetooth off and back on

**Step 2 — Capture traffic**
1. Open HomeLinking, connect to your strip
2. Change a color, turn it on and off
3. This writes the real BLE packets into the log file

**Step 3 — Pull the log**

*On Samsung (Android 13+):*
```bash
adb bugreport bugreport.zip
# Unzip and look for: FS/data/log/bt/btsnoop_hci.log
```

*On stock Android / Pixel:*
```bash
adb pull /sdcard/btsnoop_hci.log
# or
adb pull /data/misc/bluetooth/logs/btsnoop_hci.log
```

**Step 4 — Parse it**
```bash
python parse_btsnoop.py btsnoop_hci.log
```

Look for lines like:
```
[pkt  123] SENT ATT WriteCmd handle=0x0012  payload(20B): fbfbfb0a41424344000022640000000000ff000000
                                                                    ^^^^^^^^
                                                                    rolling code bytes (4 bytes after fbfbfb0a)
```

**Step 5 — Update the script**
```python
# In manka.py / manka_wled_bridge.py:
ROLLING = bytes.fromhex("YOUR8HEXCHARS")
```

---

### Method 2: iPhone + Mac with PacketLogger ⚠️ Untested

> **We haven't tried this.** The steps below are based on how Apple's PacketLogger tool works in general — if you try it, please open an issue and let us know if it worked.

Apple provides a tool called **PacketLogger** that can capture Bluetooth HCI logs from a connected iPhone, similar to Android's HCI snoop log.

**Requirements:**
- iPhone with HomeLinking installed and the MANKA strip already paired
- Mac (PacketLogger is macOS-only)
- Free Apple Developer account

**Step 1 — Get PacketLogger**
1. Sign in at [developer.apple.com/download/all](https://developer.apple.com/download/all) (free account)
2. Search for **"Additional Tools for Xcode"** and download the version matching your Xcode
3. Open the DMG → navigate to `Hardware/` → copy `PacketLogger.app` to your Applications

**Step 2 — Capture from iPhone**
1. Connect your iPhone to the Mac via USB cable
2. Open PacketLogger
3. Go to **File → New iOS Bluetooth Log** — select your iPhone
4. Open HomeLinking on your iPhone, connect to the strip, and change some colors
5. Stop the capture in PacketLogger

**Step 3 — Find the rolling code**

PacketLogger uses its own `.pklg` format. You can view ATT Write packets directly in its interface — look for 20-byte payloads starting with `fb fb fb 0a`. The 4 bytes after `fb fb fb 0a` are your rolling code.

Alternatively, export via **File → Save As** and select btsnoop format if available, then run `parse_btsnoop.py` on the output.

---

### Method 3: Windows HCI Logging ⚠️ Untested, Complex

> **We haven't tried this.** Windows can log its own Bluetooth HCI traffic, but HomeLinking runs on a phone — not Windows — so this requires an Android emulator to bridge the gap, which is significantly more complex and may not work at all (BLE support in emulators is poor).

Windows 10/11 has built-in HCI logging via a registry key:

1. Open **Registry Editor** as Administrator
2. Navigate to:
   ```
   HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters
   ```
3. Create a new DWORD value: `EnableHciLogging` = `1`
4. Reboot
5. The log will appear at `C:\Windows\Temp\bthport.log` (ETL format, not btsnoop)

The problem: this captures your *Windows machine's* Bluetooth traffic, not your phone's. To use this you'd need HomeLinking running on Windows via an Android emulator (BlueStacks, LDPlayer, etc.) with a real Bluetooth adapter passed through to the emulator — a path that is technically possible but difficult and unlikely to work reliably for BLE.

**More practical Windows alternative:** Use a dedicated BLE sniffer — see Method 4.

---

### Method 4: Hardware BLE Sniffer ⚠️ Untested, Encrypted Traffic Problem

> **We haven't tried this.** There is a significant technical obstacle described below that may make this approach unworkable for already-paired devices.

A **Nordic Semiconductor nRF52840 Dongle** (~$10 USD) flashed with nRF Sniffer firmware can passively capture BLE packets and feed them to Wireshark on any OS (Windows, Mac, Linux).

**The obstacle — BLE encryption:**

BLE connections between paired devices are encrypted using keys established during the initial pairing. A passive sniffer can only decrypt the traffic if it was present during the original pairing exchange to capture the session keys. If your device is already paired, a sniffer will see encrypted payloads it cannot read.

This *might* still work if:
- You unpair and re-pair the device with the sniffer running to capture the pairing handshake
- The device doesn't use BLE pairing/bonding at all (some cheap devices don't)

**Setup (if you want to try):**
1. Buy a [Nordic nRF52840 Dongle](https://www.nordicsemi.com/Products/Development-hardware/nRF52840-Dongle)
2. Flash with [nRF Sniffer for Bluetooth LE firmware](https://www.nordicsemi.com/Products/Development-tools/nRF-Sniffer-for-Bluetooth-LE)
3. Install Wireshark + the nRF Sniffer Wireshark plugin
4. Filter for your device MAC and look for ATT Write packets to handle `0x0012`

---

### Method 5: Check the HomeLinking App Directly 🔍 Worth Trying First

> **Quickest thing to try before anything else.**

The rolling code is derived from your HomeLinking account's `userCode`. It's possible this value is visible somewhere in the app itself without needing any packet capture.

**Try these before setting up a sniffer:**
- Open HomeLinking → Account / Profile settings → look for any "User Code", "Device Code", or ID field
- Check if the app has a "Share device" or "Invite" feature that displays a code
- On Android: check the app's local storage at `/data/data/com.hle.lhzm/shared_prefs/` (requires root or Android backup extraction)

If you find a userCode field, take the last 4 characters and convert them to their ASCII hex bytes:
```python
# Example: if your userCode ends in "AB12"
"".join(f"{ord(c):02x}" for c in "AB12")  # → "41423132"
ROLLING = bytes.fromhex("41423132")
```

---

### Why is the rolling code account-specific?

The HomeLinking app authenticates to AWS on login and receives a session token / userCode. Part of that userCode is embedded in every BLE packet as an authentication token so the device only responds to its paired account. It is **not** derived from the device MAC or any hardware identifier.

---

## Installation

### Requirements

- Python 3.9+
- [bleak](https://github.com/hbldh/bleak) 0.21+
- Windows 10/11, macOS 12+, or Linux with BlueZ

```bash
pip install bleak
```

### Clone / Download

Download `manka.py` and `manka_wled_bridge.py` (plus optionally the other scripts).

Set your rolling code in both files:
```python
ROLLING = bytes.fromhex("41424344")   # ← replace with yours (e.g. "ABCD" → "41424344")
```

Set your device MAC (check with a BLE scanner app if different):
```python
DEVICE_MAC = "AA:BB:CC:DD:EE:FF"   # ← replace with yours
```

---

## CLI Usage

```bash
python manka.py on
python manka.py off
python manka.py red
python manka.py green
python manka.py blue
python manka.py white
python manka.py warm
python manka.py cyan
python manka.py magenta
python manka.py yellow
python manka.py orange
python manka.py purple
python manka.py rgb 255 0 128          # custom RGB
python manka.py rgb 255 0 0 50         # RGB + brightness (0–100)
python manka.py bright 75              # brightness only, keeps current color

# Scene/effect exploration — probe hardware animation modes
python manka.py scene 1                # try scene_id=1 (0x22 solid mode)
python manka.py effect 0x01            # try mode byte 0x01 (0x22 = confirmed solid)
```

---

## SignalRGB Integration

The strip is exposed to SignalRGB as a **WLED device** — SignalRGB has built-in WLED support, so no custom plugin is needed.

### Architecture

```
SignalRGB (canvas effect)
    │
    │  UDP port 21324  [DRGB streaming packets]
    ▼
manka_wled_bridge.py
    │  HTTP port 80    [WLED /json/info + /json/ API]
    │
    │  BLE GATT Write to FFF3
    ▼
MANKA-LED-STRIP
```

### Setup

**Step 1 — Start the bridge (run as Administrator on Windows, port 80 requires it)**

```bash
python manka_wled_bridge.py
```

You should see:
```
WLED UDP streaming on :21324
WLED HTTP API on :80
Connecting to BLE AA:BB:CC:DD:EE:FF...
BLE connected!
```

**Step 2 — Add the device in SignalRGB**

1. Open SignalRGB
2. Go to **Home → Lighting Services → WLED**
3. In the "Discover WLED device by IP" box, type `127.0.0.1` and press Enter
4. SignalRGB calls `/json/info/` on port 80, gets back `"brand": "WLED"` and adds the device
5. Click **Link** — **"MANKA LED Strip"** is now a controllable device on your canvas

**Step 3 — Assign an effect**

Drag the MANKA LED Strip block anywhere on your SignalRGB canvas. It will follow whatever effect or ambient color is assigned to that canvas position.

### Windows Auto-Start

To have the bridge start automatically with Windows:

1. Open **Task Scheduler**
2. Click **"Create Task"** (not Basic Task)
3. **General tab:** Name it `MANKA BLE Bridge`, check **"Run with highest privileges"**
4. **Triggers:** New → At startup → Delay 30 seconds (gives Bluetooth time to initialize)
5. **Actions:** New → Start a program
   - Program: `python`
   - Arguments: `C:\Users\YourName\Desktop\manka_wled_bridge.py`
   - Start in: `C:\Users\YourName\Desktop`
6. **Settings:** Check "Run task as soon as possible after a scheduled start is missed"
7. Save — enter your Windows password when prompted

---

## Mac Mini / Home Server

The bridge runs on macOS with no code changes. The Mac mini must be within Bluetooth range (~10m) of the strip.

### macOS Setup

```bash
pip3 install bleak
```

Grant Python Bluetooth access when prompted, or go to **System Settings → Privacy & Security → Bluetooth** and add Terminal/Python.

**Port 80 workaround** (avoids running as root):

```bash
# One-time: redirect port 80 → 8080 at the OS level
echo "rdr pass on lo0 tcp from any to 127.0.0.1 port 80 -> 127.0.0.1 port 8080" | sudo pfctl -ef -
```

Then change `HTTP_PORT = 80` to `HTTP_PORT = 8080` in `manka_wled_bridge.py`.

### Auto-Start with launchd

Create `/Library/LaunchDaemons/com.manka.bridge.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.manka.bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/YourName/manka_wled_bridge.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/manka_bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/manka_bridge.log</string>
</dict>
</plist>
```

```bash
sudo launchctl load /Library/LaunchDaemons/com.manka.bridge.plist
```

`KeepAlive: true` means macOS will restart the bridge automatically if it crashes or if BLE drops.

---

## Architecture

Everything runs locally on a single machine. No cloud, no internet, no external servers.

```
╔══════════════════════════════════════════════════════════════════════╗
║                        YOUR PC / MAC MINI                           ║
║                     (localhost / 127.0.0.1 only)                    ║
║                    ✗ not reachable from internet                    ║
║                                                                      ║
║   ┌────────────────────┐      ┌─────────────────────────────────┐   ║
║   │   SignalRGB        │      │      manka_wled_bridge.py       │   ║
║   │                    │      │                                 │   ║
║   │  Canvas effect     │─────▶│  HTTP :80   (WLED discovery)   │   ║
║   │  assigns color     │ UDP  │  UDP  :21324 (color stream)     │   ║
║   │  to MANKA block    │─────▶│                                 │   ║
║   └────────────────────┘      │  Color queue (thread-safe)      │   ║
║                                │  BLE asyncio loop, max 20 Hz   │   ║
║                                └────────────────┬────────────────┘   ║
║                                                 │ Bluetooth LE       ║
╚═════════════════════════════════════════════════╪════════════════════╝
                                                  │
                                          ┌───────▼────────┐
                                          │ MANKA-LED-STRIP │
                                          │  BLE GATT FFF3  │
                                          └─────────────────┘
```

**Network boundary notes:**
- Both servers bind to `127.0.0.1` — traffic never leaves the machine
- Bluetooth is local radio only — ~10m range, no network required
- No accounts, no cloud calls, no outbound connections at runtime

---

## Files in This Repo

| File | Purpose |
|---|---|
| `manka.py` | Standalone CLI controller — on/off/colors/rgb/brightness |
| `manka_wled_bridge.py` | **Main integration** — WLED emulator + BLE bridge for SignalRGB |
| `manka_bridge.py` | Simple HTTP bridge (port 12345) — alternative if WLED approach causes issues |
| `parse_btsnoop.py` | HCI snoop log parser — use this to find your rolling code |
| `manka_test.py` | Development test script — sends a color sequence to verify the strip responds |
| `manka_query.py` | BLE query/debug tool — tests query commands and logs FFF4 responses |

---

## LED Hardware Notes

### Single-zone strip — no per-LED addressing

The SUNMON boom arm contains a multi-LED strip but the entire strip is driven as a **single zone**. There is no way to address individual LEDs through the known protocol.

This was confirmed by sweeping all 256 mode bytes (0x00–0xFF) and observing the results:

- Every mode affects the entire strip simultaneously — no chasing, no segmented colors
- Some mode bytes trigger built-in animations (fades, breathing) which confirm the strip has many LEDs driven by PWM
- No mode produced independent color control of different LEDs

The protocol sends a single RGB triplet per packet (`r, g, b` at offsets 16–18). There is no pixel index, pixel count, or per-LED payload field anywhere in the packet format.

**Practical implication:** For SignalRGB or any other ambient lighting tool, the strip should be configured as a **1-pixel device**. Sending multiple pixels serves no purpose — only the first (or averaged) color will apply.

---

## Future Work

- [ ] **Apple HomeKit / Homebridge** — expose the strip as a HomeKit accessory via a Homebridge plugin

---

## Acknowledgements

Protocol discovered through Android HCI Bluetooth snoop log capture + `parse_btsnoop.py`. The HomeLinking APK decompile (JADX) provided useful structural context but the exact working packet bytes only became clear from the live capture — if you're trying to do something similar, **skip straight to the HCI log**.

---

## Legal

This project was developed for personal interoperability use with hardware the author owns. Reverse engineering for interoperability purposes is permitted under DMCA §1201(f) (US) and equivalent provisions in other jurisdictions.

This project is not affiliated with, endorsed by, or connected to Manka, HomeLinking, SUNMON, or any related company. All trademarks are property of their respective owners. The HomeLinking APK was used solely for local analysis and is not distributed here.

Use of this project is at your own risk and subject to the laws of your jurisdiction. The authors are not responsible for any misuse.
