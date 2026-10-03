#!/usr/bin/env python3
"""
Check Flipper Zero BLE connection status.
"""

import asyncio

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flip_config import get_flipper_address
from bleak import BleakClient, BleakScanner

FLIPPER_ADDRESS = get_flipper_address()
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"


async def check_status():
    """Check if Flipper is connected and responsive."""
    print(f"Checking Flipper Zero at {FLIPPER_ADDRESS}...")

    # First try to find it via scan
    print("Scanning for nearby BLE devices...")
    devices = await BleakScanner.discover(timeout=3.0)

    flipper_found = None
    for device in devices:
        if device.address.upper() == FLIPPER_ADDRESS.upper():
            flipper_found = device
            break
        # Also check by name
        if device.name and "Flipper" in device.name:
            print(f"  Found Flipper: {device.name} ({device.address})")

    if flipper_found:
        print(f"Found Flipper in scan: {flipper_found.name or 'Unknown'}")
    else:
        print(f"Flipper not found in scan (may still be connectable)")

    # Try to connect
    print(f"\nAttempting connection to {FLIPPER_ADDRESS}...")
    try:
        async with BleakClient(FLIPPER_ADDRESS, timeout=5) as client:
            if client.is_connected:
                print("Connected successfully!")

                # Check for serial service
                services = client.services
                serial_found = False
                for service in services:
                    for char in service.characteristics:
                        if RX_CHAR_UUID.lower() in char.uuid.lower():
                            serial_found = True
                            break

                if serial_found:
                    print("Serial profile available - Claude Controller app is running")
                    print("\nStatus: READY")
                    return 0
                else:
                    print("Serial profile not found - is Claude Controller app running?")
                    print("\nStatus: APP NOT RUNNING")
                    return 1
            else:
                print("Connection failed")
                print("\nStatus: DISCONNECTED")
                return 1

    except Exception as e:
        print(f"Connection error: {e}")
        print("\nStatus: UNREACHABLE")
        return 1


def main():
    try:
        result = asyncio.run(check_status())
        sys.exit(result)
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(1)


if __name__ == "__main__":
    main()
