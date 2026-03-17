"""
Parse btsnoop_hci.log and extract ATT Write commands to FFF3.
Usage: python parse_btsnoop.py btsnoop.log

Use this to find your rolling code — look for FBFBFB packets and read
bytes 4-7 of the payload. See README for full instructions.
"""
import struct
import sys
import re

BTSNOOP_MAGIC = b"btsnoop\x00"

def parse_btsnoop(path):
    with open(path, "rb") as f:
        header = f.read(16)
        if not header.startswith(BTSNOOP_MAGIC):
            print("Not a btsnoop file!")
            return

        version, datalink = struct.unpack(">II", header[8:])
        print(f"btsnoop v{version}, datalink={datalink}\n")

        packets = []
        pkt_num = 0
        while True:
            rec_hdr = f.read(24)
            if len(rec_hdr) < 24:
                break
            orig_len, inc_len, flags, drops, ts_us_hi, ts_us_lo = struct.unpack(">IIIIII", rec_hdr)
            data = f.read(inc_len)
            pkt_num += 1
            packets.append((pkt_num, flags, data))

    print(f"Total packets: {pkt_num}\n")

    # Filter for HCI_ACL packets (datalink=1001 = H4, first byte 0x02 = ACL)
    # flags: bit0=0 sent, bit0=1 received
    writes = []
    for num, flags, data in packets:
        if len(data) < 1:
            continue

        # H4 transport: first byte is type
        if data[0] != 0x02:  # HCI ACL
            continue
        if len(data) < 5:
            continue

        # ACL header: handle(12)+pb(2)+bc(2) flags, total_len
        acl_handle_flags = struct.unpack_from("<H", data, 1)[0]
        acl_len = struct.unpack_from("<H", data, 3)[0]
        acl_data = data[5:5+acl_len]

        if len(acl_data) < 4:
            continue

        # L2CAP
        l2cap_len = struct.unpack_from("<H", acl_data, 0)[0]
        l2cap_cid = struct.unpack_from("<H", acl_data, 2)[0]
        if l2cap_cid != 0x0004:  # ATT CID
            continue
        att_data = acl_data[4:]
        if len(att_data) < 1:
            continue

        att_opcode = att_data[0]
        direction = "SENT" if (flags & 1) == 0 else "RECV"

        # ATT Write Command (0x52) = write-without-response
        # ATT Write Request (0x12) = write-with-response
        if att_opcode in (0x52, 0x12):
            if len(att_data) < 3:
                continue
            handle = struct.unpack_from("<H", att_data, 1)[0]
            payload = att_data[3:]
            verb = "WriteCmd" if att_opcode == 0x52 else "WriteReq"
            writes.append((num, direction, handle, payload))
            print(f"[pkt {num:5d}] {direction} ATT {verb} handle=0x{handle:04x}  payload({len(payload)}B): {payload.hex()}")
            # Flag FBFBFB packets — your rolling code is bytes 4-7
            if payload[:3] == b'\xfb\xfb\xfb':
                print(f"           ^^^ FBFBFB cmd=0x{payload[3]:02x}  rolling={payload[4:8].hex()}")
            # Flag suspected WiCom packets (28 bytes)
            if len(payload) == 28:
                print(f"           ^^^ 28-byte WiCom candidate")

        # ATT Handle Value Notification (0x1b) = notify
        elif att_opcode == 0x1b:
            handle = struct.unpack_from("<H", att_data, 1)[0]
            payload = att_data[3:]
            print(f"[pkt {num:5d}] {direction} ATT Notify  handle=0x{handle:04x}  payload({len(payload)}B): {payload.hex()}")

    print(f"\n--- {len(writes)} ATT writes found ---")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_btsnoop.py <btsnoop.log>")
        sys.exit(1)
    parse_btsnoop(sys.argv[1])
