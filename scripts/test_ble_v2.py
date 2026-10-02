#!/usr/bin/env python3
"""
Test with 64fe0000 characteristic (has read+write+notify)
"""

import asyncio
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from flip_config import get_flipper_address
from bleak import BleakClient

FLIPPER_ADDRESS = get_flipper_address()
SERIAL_SERVICE_UUID = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"

# Try the bidirectional characteristic
TX_RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e64fe0000"

received_data = []

def notification_handler(sender, data):
    text = data.decode('utf-8', errors='replace')
    print(f"📥 Received: {text!r}")
    received_data.append(text)

async def main():
    print(f"🔗 Connecting to Flipper at {FLIPPER_ADDRESS}...")

    async with BleakClient(FLIPPER_ADDRESS) as client:
        print(f"✅ Connected!")

        # Subscribe to notifications
        print(f"\n📡 Subscribing to {TX_RX_CHAR_UUID[-8:]}...")
        await client.start_notify(TX_RX_CHAR_UUID, notification_handler)
        print("✅ Subscribed!")

        # Send test message to TX characteristic
        TX_CHAR = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
        message = "hello world\n"
        print(f"\n📤 Sending to TX ({TX_CHAR[-8:]}): {message!r}")
        # Use write-without-response since that's what the char supports
        await client.write_gatt_char(TX_CHAR, message.encode(), response=False)
        print("✅ Sent!")

        # Wait for response
        print("\n⏳ Waiting 5 seconds for response...")
        await asyncio.sleep(5)

        if received_data:
            print(f"\n🎉 SUCCESS! Received: {received_data}")
        else:
            print("\n⚠️  No response received")
            print("\nLet me try reading characteristics directly...")

            for uuid in ["19ed82ae-ed21-4c9d-4145-228e61fe0000",
                         "19ed82ae-ed21-4c9d-4145-228e63fe0000",
                         "19ed82ae-ed21-4c9d-4145-228e64fe0000"]:
                try:
                    data = await client.read_gatt_char(uuid)
                    print(f"  {uuid[-8:]}: {data}")
                except Exception as e:
                    print(f"  {uuid[-8:]}: {e}")

        await client.stop_notify(TX_RX_CHAR_UUID)

if __name__ == "__main__":
    asyncio.run(main())
