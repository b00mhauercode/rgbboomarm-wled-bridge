# ── Your personal device configuration ────────────────────────────────────────
# Copy this file to config_local.py and fill in your values.
# config_local.py is gitignored and will never be committed.
#
# How to find your values:
#   DEVICE_MAC  — use a BLE scanner app (e.g. nRF Connect) to find the MAC
#   ROLLING     — capture an HCI snoop log and run parse_btsnoop.py (see README)
#   WLED_MAC    — your DEVICE_MAC with colons removed, e.g. "2109095203FD"
# ──────────────────────────────────────────────────────────────────────────────

DEVICE_MAC = "XX:XX:XX:XX:XX:XX"
ROLLING    = "XXXXXXXX"   # 8 hex chars = 4 bytes
WLED_MAC   = "XXXXXXXXXXXX"  # 12 hex chars, no colons
