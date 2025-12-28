#!/usr/bin/env python3
"""
Claude Code permission hook - routes requests to Flipper Zero.
Reads JSON from stdin, sends to Flipper via BLE, returns decision.
"""

import asyncio
import json
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bleak import BleakClient

# Flipper BLE Serial UUIDs
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"

# Flipper address - TODO: make configurable
FLIPPER_ADDRESS = os.environ.get("FLIPPER_ADDRESS", "80:E1:26:71:4C:EA")

TIMEOUT = 300  # 5 minutes max wait for user response


async def send_permission_request(request_text: str) -> str:
    """Send request to Flipper and wait for Y/N response."""
    response = None
    got_ack = False

    def on_notify(sender, data: bytes):
        nonlocal response, got_ack
        text = data.decode().strip()
        if text == "ACK":
            got_ack = True
        elif text in ("Y", "N"):
            response = text

    async with BleakClient(FLIPPER_ADDRESS, timeout=10) as client:
        await client.start_notify(RX_CHAR_UUID, on_notify)

        # Send the request
        await client.write_gatt_char(
            TX_CHAR_UUID, (request_text + "\n").encode(), response=False
        )

        # Wait for response
        for _ in range(TIMEOUT):
            await asyncio.sleep(1)
            if response:
                break

        await client.stop_notify(RX_CHAR_UUID)

    return response


def main():
    # Read request from stdin (Claude Code sends JSON)
    try:
        request_json = json.load(sys.stdin)
    except json.JSONDecodeError:
        print('{"decision": "deny", "error": "Invalid JSON input"}')
        sys.exit(1)

    # Extract relevant info for display
    tool_name = request_json.get("tool", {}).get("name", "Unknown")
    command = ""

    # For Bash commands, show the command
    if tool_name == "Bash":
        params = request_json.get("tool", {}).get("params", {})
        command = params.get("command", "")[:50]  # Truncate for display

    # Build display message
    if command:
        display_msg = f"{tool_name}: {command}"
    else:
        display_msg = f"Allow {tool_name}?"

    # Truncate if too long for Flipper display
    display_msg = display_msg[:60]

    try:
        response = asyncio.run(send_permission_request(display_msg))

        if response == "Y":
            print(json.dumps({"decision": "allow"}))
        elif response == "N":
            print(json.dumps({"decision": "deny"}))
        else:
            # Timeout or no response - deny by default
            print(json.dumps({"decision": "deny", "reason": "timeout"}))

    except Exception as e:
        # BLE connection failed - deny for safety
        print(json.dumps({"decision": "deny", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
