#!/usr/bin/env python3
"""
Test RPC characteristic (64fe) which has read+write+notify
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from flip_config import get_flipper_address
from bleak import BleakClient

FLIPPER_ADDRESS = get_flipper_address()
RPC_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e64fe0000"
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"

received_data = []

def handler(sender, data):
    print(f"📥 Received ({len(data)} bytes): {data.hex()} = {data}")
    received_data.append(data)

async def main():
    print(f"🔗 Connecting to {FLIPPER_ADDRESS}...")

    async with BleakClient(FLIPPER_ADDRESS) as client:
        print(f"✅ Connected!")

        # Subscribe to ALL serial chars
        for uuid in ["19ed82ae-ed21-4c9d-4145-228e61fe0000",
                     "19ed82ae-ed21-4c9d-4145-228e63fe0000",
                     "19ed82ae-ed21-4c9d-4145-228e64fe0000"]:
            try:
                await client.start_notify(uuid, handler)
                print(f"  ✅ Subscribed to {uuid[-8:]}")
            except Exception as e:
                print(f"  ❌ {uuid[-8:]}: {e}")

        # Small delay after connect
        print("\n⏳ Waiting 1s after connect...")
        await asyncio.sleep(1)

        # Send hello world
        msg = b"hello world\n"
        print(f"\n📤 Sending {msg!r} to TX (62fe)...")
        await client.write_gatt_char(TX_CHAR_UUID, msg, response=False)
        print("✅ Sent!")

        # Wait for processing and response
        print("\n⏳ Waiting 3s for response...")
        await asyncio.sleep(3)

        # Try reading to trigger indication delivery
        print("\n📖 Reading 61fe to check for response...")
        try:
            data = await client.read_gatt_char("19ed82ae-ed21-4c9d-4145-228e61fe0000")
            if any(b != 0 for b in data):
                print(f"  Response data: {data}")
        except Exception as e:
            print(f"  Read error: {e}")

        if received_data:
            print(f"\n🎉 Total received: {len(received_data)} packets")
            for pkt in received_data:
                print(f"  - {pkt}")
        else:
            print("\n⚠️  No data received")

if __name__ == "__main__":
    asyncio.run(main())
