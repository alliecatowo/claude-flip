#!/usr/bin/env python3
"""
Claude Code StopTool hook - notifies Flipper that a tool completed.
This clears any pending permission request on the Flipper display.
"""

import asyncio
import sys
import os

from bleak import BleakClient

# Flipper BLE Serial UUIDs
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"

# Flipper address
FLIPPER_ADDRESS = os.environ.get("FLIPPER_ADDRESS", "80:E1:26:71:4C:EA")

def log_debug(msg):
    with open("/tmp/flipper_stop_debug.log", "a") as f:
        f.write(f"{msg}\n")

async def notify_done():
    """Send DONE message to Flipper to clear pending request."""
    log_debug("=== stop_hook running ===")
    try:
        log_debug(f"Connecting to {FLIPPER_ADDRESS}...")
        async with BleakClient(FLIPPER_ADDRESS, timeout=2) as client:
            log_debug("Connected, sending DONE...")
            await client.write_gatt_char(
                TX_CHAR_UUID, b"DONE\n", response=False
            )
            log_debug("DONE sent!")
    except Exception as e:
        log_debug(f"Error: {e}")


def main():
    # Just notify Flipper and exit quickly
    asyncio.run(notify_done())
    sys.exit(0)


if __name__ == "__main__":
    main()
