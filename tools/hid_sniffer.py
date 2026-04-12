"""Dell Peripheral HID Sniffer.

Listens for HID Input Reports from the Dell Secure Link Receiver
while you change settings in Dell Peripheral Manager (DDPM).

Usage:
    python tools/hid_sniffer.py

Instructions:
    1. Run this script
    2. Open Dell Display and Peripheral Manager
    3. Change a setting (e.g., KB900 backlight, MS900 DPI)
    4. Watch the output for HID report changes
    5. Press Ctrl+C to stop
"""

from __future__ import annotations

import sys
import time

import hid


def main() -> None:
    print("Dell Peripheral HID Sniffer")
    print("=" * 40)
    print()

    # Find all Dell Secure Link Receiver interfaces
    dell_devs = [
        d for d in hid.enumerate() if d["vendor_id"] == 0x413C and d["product_id"] == 0x2119
    ]
    print(f"Found {len(dell_devs)} Dell Secure Link Receiver interfaces:")
    for d in dell_devs:
        print(f"  UP=0x{d['usage_page']:04X} U=0x{d['usage']:04X} IF={d['interface_number']}")
    print()

    # Open all interfaces and listen for input reports
    handles: list[tuple[hid.device, dict]] = []
    for d in dell_devs:
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(1)
            handles.append((h, d))
            print(f"Opened UP=0x{d['usage_page']:04X} IF={d['interface_number']}")
        except Exception as e:
            print(f"Failed to open UP=0x{d['usage_page']:04X}: {e}")

    # Also open the WB7022 webcam
    wb_devs = [
        d for d in hid.enumerate() if d["vendor_id"] == 0x413C and d["product_id"] == 0xD001
    ]
    for d in wb_devs:
        try:
            h = hid.device()
            h.open_path(d["path"])
            h.set_nonblocking(1)
            handles.append((h, d))
            print(f"Opened WB7022 UP=0x{d['usage_page']:04X}")
        except Exception as e:
            print(f"Failed to open WB7022 UP=0x{d['usage_page']:04X}: {e}")

    if not handles:
        print("No devices opened. Exiting.")
        sys.exit(1)

    print()
    print("Listening for HID Input Reports...")
    print("Change settings in DDPM now. Press Ctrl+C to stop.")
    print("-" * 60)

    # Also periodically poll Feature Report 0x09 for changes
    last_feature: bytes = b""
    feature_handle = None
    for h, d in handles:
        if d["usage_page"] == 0xFF02:
            feature_handle = h

    try:
        while True:
            for h, d in handles:
                try:
                    max_len = 32 if d["usage_page"] < 0xFF00 else 512
                    data = h.read(max_len)
                except OSError:
                    continue
                if data:
                    ts = time.strftime("%H:%M:%S")
                    hex_str = " ".join(f"{b:02X}" for b in data[:48])
                    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data[:48])
                    up = f"0x{d['usage_page']:04X}"
                    pid = f"0x{d['product_id']:04X}"
                    print(f"[{ts}] PID={pid} UP={up} ({len(data)} bytes)")
                    print(f"  HEX:   {hex_str}")
                    print(f"  ASCII: {ascii_part}")
                    print()

            # Poll feature report every 2 seconds for changes
            if feature_handle:
                try:
                    data = feature_handle.get_feature_report(0x09, 512)
                    raw = bytes(data)
                    if raw != last_feature and any(b != 0 for b in raw[1:]):
                        ts = time.strftime("%H:%M:%S")
                        hex_str = " ".join(f"{b:02X}" for b in raw[:48])
                        print(f"[{ts}] FEATURE REPORT 0x09 CHANGED:")
                        print(f"  HEX: {hex_str}")
                        if last_feature:
                            # Show diff
                            for i, (a, b) in enumerate(zip(last_feature, raw, strict=False)):
                                if a != b:
                                    print(f"  DIFF byte[{i}]: 0x{a:02X} -> 0x{b:02X}")
                        print()
                        last_feature = raw
                except Exception:
                    pass

            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
        print("Stopped.")

    for h, _ in handles:
        h.close()


if __name__ == "__main__":
    main()
