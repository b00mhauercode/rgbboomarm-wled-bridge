# CLAUDE.md — rgbboomarm-controller

## What this is
Python BLE controller for the **SUNMON RGB Boom Arm** LED strip (BLE name: `MANKA-LED-STRIP`).
Reverse engineered from Android HCI snoop logs. See README for full protocol documentation.

## Key files
| File | Role |
|---|---|
| `manka_proto.py` | **Shared protocol module** — UUIDs, `pkt_color`, `pkt_off`. All scripts import from here. |
| `manka.py` | Standalone CLI — on/off/colors/rgb/brightness/scene/effect |
| `manka_wled_bridge.py` | **Main integration** — emulates a WLED device for SignalRGB |
| `manka_bridge.py` | Simpler HTTP bridge alternative (port 12345, no WLED emulation) |
| `manka_query.py` | Debug/RE tool — sends query commands, logs FFF4 notifications |
| `manka_test.py` | Dev test — sends a color sequence to verify the strip responds |
| `parse_btsnoop.py` | Parses Android HCI snoop logs to extract the rolling code |
| `config.py` | Placeholder config (committed) |
| `config_local.py` | Real device config — **gitignored, never commit** |

## Device config
All scripts load config via:
```python
from manka_proto import DEVICE_MAC, ROLLING  # ROLLING is already bytes
```
`manka_wled_bridge.py` additionally imports `WLED_MAC` directly from config_local/config.

User must create `config_local.py` (copy of `config.py`) with their real `DEVICE_MAC`, `ROLLING`, and `WLED_MAC`.

## Protocol essentials
- BLE characteristic `FFF3` (write) — send all control packets here
- BLE characteristic `FFF4` (notify) — must subscribe before writing or device ignores commands
- Packet: 20 bytes, magic `0xFB 0xFB 0xFB 0x0A` + 4-byte rolling code + 12 bytes payload
- Rolling code = ASCII bytes of last 4 chars of HomeLinking account `userCode`
- Mode byte `0x22` = solid color ON, `0x00` = OFF
- **Single-zone device** — entire strip is one color, no per-LED addressing

## Scratch scripts
`test_*.py` files are gitignored. Use this pattern for throwaway experiments.

## Dependencies
```
pip install bleak
```
Python 3.9+. On Windows, `manka_wled_bridge.py` requires Administrator for port 80.
