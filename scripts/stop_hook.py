#!/usr/bin/env python3
"""
Claude Code PostToolUse hook - notifies Flipper that a tool completed.
"""

import asyncio
import sys
import os

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from flip_config import get_flipper_address
from bleak import BleakClient, BleakScanner

TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
FLIPPER_ADDRESS = get_flipper_address()

def log(msg):
    with open("/tmp/stop_hook.log", "a") as f:
        f.write(f"{msg}\n")

async def notify_done():
    log("=== stop_hook v2 ===")
    
    for attempt in range(3):
        try:
            if attempt > 0:
                log(f"Retry scan...")
                await BleakScanner.discover(timeout=1)
            
            log(f"Try {attempt+1}...")
            async with BleakClient(FLIPPER_ADDRESS, timeout=10) as client:
                await client.write_gatt_char(TX_CHAR_UUID, b"DONE\n", response=False)
                log("DONE sent!")
                return
        except Exception as e:
            log(f"Err: {e}")


def main():
    asyncio.run(notify_done())


if __name__ == "__main__":
    main()
