#!/usr/bin/env python3
"""
Test raw CLI over BLE - no RPC, just simple serial communication.
Start the Claude Controller app on your Flipper FIRST, then run this.
"""

import asyncio
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from flip_config import get_flipper_address
from bleak import BleakClient

# Flipper BLE Serial UUIDs
SERIAL_SERVICE_UUID = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # Host -> Flipper
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper -> Host

FLIPPER_ADDRESS = get_flipper_address()

received_data = bytearray()

def notification_handler(sender, data: bytes):
    """Handle incoming BLE notifications."""
    print(f"RX: {data!r}")
    received_data.extend(data)

async def main():
    print(f"Connecting to Flipper at {FLIPPER_ADDRESS}...")
    print("Make sure Claude Controller app is running on Flipper!")

    async with BleakClient(FLIPPER_ADDRESS) as client:
        print("Connected!")

        # Subscribe to RX notifications
        await client.start_notify(RX_CHAR_UUID, notification_handler)

        # Send a simple message - just raw text, no RPC
        message = b"hello flipper\r\n"
        print(f"Sending: {message!r}")
        await client.write_gatt_char(TX_CHAR_UUID, message, response=False)

        # Wait for response
        print("Waiting for response...")
        await asyncio.sleep(3)

        if received_data:
            print(f"Got response: {received_data!r}")
        else:
            print("No response received")

        # Try another message
        message2 = b"test message\r\n"
        print(f"Sending: {message2!r}")
        await client.write_gatt_char(TX_CHAR_UUID, message2, response=False)

        await asyncio.sleep(2)
        print(f"Total received: {received_data!r}")

if __name__ == "__main__":
    asyncio.run(main())
