#!/usr/bin/env python3
"""
Send a test message to Flipper Zero and wait for response.
"""

import asyncio
import os
import sys

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from flip_config import get_flipper_address
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

FLIPPER_ADDRESS = get_flipper_address()
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"


async def test_connection():
    """Send test message and wait for user response."""
    response = None
    got_ack = False

    def on_notify(sender: BleakGATTCharacteristic, data: bytearray):
        nonlocal response, got_ack
        text = data.decode().strip()
        print(f"  Received: {text}")
        if text == "ACK":
            got_ack = True
        elif text in ("Y", "N", "A", "D"):
            response = text

    print(f"Connecting to Flipper at {FLIPPER_ADDRESS}...")

    try:
        async with BleakClient(FLIPPER_ADDRESS, timeout=10) as client:
            print("Connected!")
            await client.start_notify(RX_CHAR_UUID, on_notify)

            # Send test message
            test_msg = "TEST: Press any button"
            print(f"Sending: {test_msg}")
            await client.write_gatt_char(
                TX_CHAR_UUID, (test_msg + "\n").encode(), response=False
            )

            # Wait for response (30 second timeout)
            print("Waiting for button press on Flipper...")
            for i in range(30):
                await asyncio.sleep(1)
                if response:
                    break
                if i % 5 == 4:
                    print(f"  Still waiting... ({30 - i - 1}s remaining)")

            await client.stop_notify(RX_CHAR_UUID)

            if response:
                responses = {
                    "Y": "Allow (OK/Right)",
                    "N": "Deny (Left)",
                    "A": "Allow Always (Up)",
                    "D": "Deny Always (Down)"
                }
                print(f"\nTest PASSED!")
                print(f"  Response: {response} - {responses.get(response, 'Unknown')}")
                return 0
            else:
                print("\nTest FAILED: No response received (timeout)")
                return 1

    except Exception as e:
        print(f"\nTest FAILED: {e}")
        return 1


def main():
    try:
        result = asyncio.run(test_connection())
        sys.exit(result)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(1)


if __name__ == "__main__":
    main()
