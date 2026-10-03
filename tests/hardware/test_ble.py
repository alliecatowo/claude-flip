#!/usr/bin/env python3
"""
Test BLE serial communication with Claude Controller.
Start the app on Flipper first, then run this.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from flip_config import get_flipper_address
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

# Flipper BLE Serial UUIDs
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # Host -> Flipper
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper -> Host

FLIPPER_ADDRESS = get_flipper_address()

received = bytearray()

def on_notify(sender: BleakGATTCharacteristic, data: bytearray):
    print(f"RX: {data!r}")
    received.extend(data)

async def main():
    print(f"Connecting to Flipper at {FLIPPER_ADDRESS}...")
    print("Make sure Claude Controller app is running!")

    async with BleakClient(FLIPPER_ADDRESS) as client:
        print("Connected!")

        # Subscribe to notifications
        await client.start_notify(RX_CHAR_UUID, on_notify)

        # Send test message
        msg = b"Hello Flipper!\n"
        print(f"Sending: {msg!r}")
        await client.write_gatt_char(TX_CHAR_UUID, msg, response=False)

        # Wait for response
        print("Waiting for response (press Y or N on Flipper)...")
        for _ in range(30):
            await asyncio.sleep(1)
            if received:
                print(f"Got: {bytes(received)!r}")
                break
        else:
            print("No response within 30s")

if __name__ == "__main__":
    asyncio.run(main())
