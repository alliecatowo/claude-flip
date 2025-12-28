#!/usr/bin/env python3
"""
Test all notify characteristics to find the one receiving data
"""

import asyncio
from bleak import BleakClient

FLIPPER_ADDRESS = "80:E1:26:71:4C:EA"
SERIAL_SERVICE_UUID = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"
SERIAL_TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"

received_data = {}

def make_handler(char_uuid):
    def handler(sender, data):
        text = data.decode('utf-8', errors='replace')
        print(f"📥 [{char_uuid[-8:]}] Received: {text!r}")
        received_data[char_uuid] = text
    return handler

async def main():
    print(f"🔗 Connecting to Flipper at {FLIPPER_ADDRESS}...")

    async with BleakClient(FLIPPER_ADDRESS) as client:
        print(f"✅ Connected!")

        tx_char = None
        notify_chars = []

        # Find serial service
        for service in client.services:
            if service.uuid.lower() == SERIAL_SERVICE_UUID.lower():
                print(f"\n📋 Serial Service characteristics:")
                for char in service.characteristics:
                    props = ",".join(char.properties)
                    print(f"  {char.uuid} [{props}]")

                    # 62fe is the TX char (write-without-response)
                    if "write-without-response" in char.properties:
                        tx_char = char
                    if "notify" in char.properties or "indicate" in char.properties:
                        notify_chars.append(char)

        if not tx_char:
            print("❌ No TX characteristic found!")
            return

        # Subscribe to ALL notify/indicate chars
        print(f"\n📡 Subscribing to {len(notify_chars)} characteristics...")
        for char in notify_chars:
            try:
                await client.start_notify(char.uuid, make_handler(char.uuid))
                print(f"  ✅ Subscribed to {char.uuid[-8:]}")
            except Exception as e:
                print(f"  ❌ Failed {char.uuid[-8:]}: {e}")

        # Send test message (use write-without-response)
        message = "hello world\n"
        print(f"\n📤 Sending: {message!r} to {tx_char.uuid[-8:]}")
        await client.write_gatt_char(tx_char.uuid, message.encode(), response=False)
        print("✅ Sent!")

        # Wait and check
        print("\n⏳ Waiting 5 seconds for response...")
        await asyncio.sleep(5)

        if received_data:
            print(f"\n🎉 Data received on: {list(received_data.keys())}")
            for uuid, data in received_data.items():
                print(f"  {uuid[-8:]}: {data}")
        else:
            print("\n⚠️  No data received on any characteristic")

        # Cleanup
        for char in notify_chars:
            try:
                await client.stop_notify(char.uuid)
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
