#!/usr/bin/env python3
"""
Test connection to Flipper Zero via BLE or USB Serial.

Usage:
    python test_connection.py --ble           # Test BLE connection
    python test_connection.py --usb           # Test USB serial connection
    python test_connection.py                 # Test auto-detection (BLE first)
"""

import asyncio
import argparse
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flipper_bridge import FlipperBridge, ConnectionType, FlipperMessage


async def test_connection(connection_type: ConnectionType):
    """Test connection to Flipper Zero."""
    print(f"\n{'='*50}")
    print(f"Testing Flipper Zero Connection")
    print(f"Mode: {connection_type.value}")
    print(f"{'='*50}\n")

    bridge = FlipperBridge(connection_type=connection_type)

    print("Attempting to connect...")
    if await bridge.connect():
        print("Connected successfully!\n")

        # Send a test permission request
        print("Sending test permission request...")
        print("  Tool: Bash")
        print("  Summary: npm install (TEST)")
        print("  Risk: low")
        print("\n>>> On your Flipper, press:")
        print("    Right = Allow")
        print("    Left = Deny")
        print("    Down = Allow & Remember")
        print("\nWaiting for response (timeout: 30s)...")

        response = await bridge.send_permission_request(
            request_id="test001",
            tool="Bash",
            summary="npm install (TEST)",
            risk="low"
        )

        if response:
            print(f"\nReceived response!")
            print(f"  Action: {response.action}")
            if response.pattern:
                print(f"  Pattern: {response.pattern}")
        else:
            print("\nNo response received (timeout or error)")

        await bridge.disconnect()
        print("\nDisconnected")
    else:
        print("Failed to connect!")
        print("\nTroubleshooting:")
        if connection_type == ConnectionType.BLE:
            print("  - Make sure Flipper is in BLE mode (Bluetooth enabled)")
            print("  - Check that Flipper's name is 'Flipper' (or update ble_name)")
            print("  - Make sure the Claude Controller app is running on Flipper")
        else:
            print("  - Close qFlipper if it's running")
            print("  - Check that /dev/ttyACM0 exists")
            print("  - Make sure you have permission (dialout group or ACL)")


def main():
    parser = argparse.ArgumentParser(description="Test Flipper Zero connection")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ble", action="store_true", help="Test BLE connection only")
    group.add_argument("--usb", action="store_true", help="Test USB serial connection only")
    args = parser.parse_args()

    if args.ble:
        connection_type = ConnectionType.BLE
    elif args.usb:
        connection_type = ConnectionType.USB_SERIAL
    else:
        connection_type = ConnectionType.AUTO

    asyncio.run(test_connection(connection_type))


if __name__ == "__main__":
    main()
