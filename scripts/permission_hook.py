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


async def send_permission_request(request_text: str) -> tuple[str, str]:
    """Send request to Flipper and wait for response.

    Returns:
        tuple: (response, pattern) where response is Y/N/A/D and pattern is
               the tool pattern for remember decisions.
    """
    response = None
    got_ack = False

    def on_notify(sender, data: bytes):
        nonlocal response, got_ack
        text = data.decode().strip()
        if text == "ACK":
            got_ack = True
        elif text in ("Y", "N", "A", "D"):
            # Y = allow, N = deny, A = allow always, D = deny always
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


def log_debug(msg):
    """Write debug info to a file."""
    with open("/tmp/flipper_hook_debug.log", "a") as f:
        f.write(f"{msg}\n")


def main():
    log_debug("=== Hook started ===")

    # Read request from stdin (Claude Code sends JSON)
    try:
        request_json = json.load(sys.stdin)
        log_debug(f"Input: {json.dumps(request_json)}")
    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
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

        def make_response(behavior: str, message: str = None):
            """Build proper hook response format with wrapper."""
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {
                        "behavior": behavior
                    }
                }
            }
            if message:
                result["hookSpecificOutput"]["decision"]["message"] = message
            return result

        log_debug(f"Flipper response: {response}")

        if response == "Y" or response == "A":
            # Allow (per docs: use "allow" not "approve")
            output = json.dumps(make_response("allow"))
            log_debug(f"Output: {output}")
            print(output)
            sys.exit(0)
        elif response == "N" or response == "D":
            # Deny (per docs: use "deny" not "block")
            output = json.dumps(make_response("deny", "Denied via Flipper Zero"))
            log_debug(f"Output: {output}")
            print(output)
            sys.exit(0)
        else:
            # Timeout or no response - deny by default
            output = json.dumps(make_response("deny", "Timeout waiting for Flipper response"))
            log_debug(f"Output (timeout): {output}")
            print(output)
            sys.exit(0)

    except Exception as e:
        # BLE connection failed - deny for safety
        log_debug(f"Exception: {e}")
        error_output = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                    "message": f"Flipper connection failed: {e}"
                }
            }
        }
        print(json.dumps(error_output))
        sys.exit(0)  # Exit 0 so JSON is processed


if __name__ == "__main__":
    main()
