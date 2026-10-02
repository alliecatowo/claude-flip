#!/usr/bin/env python3
"""
Flipper AI Pager - MCP Server

Exposes tools for Claude to send notifications to Flipper Zero.

Tools:
  - page(message, pattern, auto_dismiss) - Send message with vibration
  - vibrate(pattern) - Just vibrate, no message
"""

import asyncio
import os
import sys
from typing import Literal

from mcp.server.fastmcp import FastMCP
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from flip_config import get_flipper_address
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flip_config import get_flipper_address  # noqa: E402
from bleak import BleakClient, BleakScanner  # noqa: E402

# Flipper BLE Serial UUIDs
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"

# Flipper address
FLIPPER_ADDRESS = get_flipper_address()

# MCP Server
mcp = FastMCP("flipper-pager")


async def send_to_flipper(message: str, max_retries: int = 5) -> str:
    """Send a message to Flipper via BLE with robust retry logic."""
    last_error = None

    for attempt in range(max_retries):
        try:
            # Scan and find the device directly (more reliable than address lookup)
            devices = await BleakScanner.discover(timeout=3)
            device = next((d for d in devices if d.address == FLIPPER_ADDRESS), None)

            if not device:
                raise Exception(f"Flipper not found in scan (attempt {attempt + 1})")

            # Use the discovered device object directly
            async with BleakClient(device, timeout=10) as client:
                await client.write_gatt_char(
                    TX_CHAR_UUID,
                    (message + "\n").encode(),
                    response=False
                )
                return "sent"

        except Exception as e:
            last_error = e
            continue

    raise last_error if last_error else Exception("BLE connection failed")


@mcp.tool()
async def page(
    message: str,
    pattern: Literal["short", "long", "urgent", "silent"] = "short",
    auto_dismiss: bool = False
) -> str:
    """
    Send a notification to the Flipper Zero.

    Args:
        message: Text to display on Flipper (max 60 chars)
        pattern: Vibration pattern - short (default), long, urgent, or silent
        auto_dismiss: If true, message auto-clears after 5 seconds

    Returns:
        Status message indicating success or failure
    """
    # Truncate message to 60 chars
    message = message[:60]

    # Format: PAGE:<pattern>:<auto>:<message>
    auto_flag = "1" if auto_dismiss else "0"
    payload = f"PAGE:{pattern}:{auto_flag}:{message}"

    try:
        await send_to_flipper(payload)
        return f"Paged Flipper: '{message}'"
    except Exception as e:
        return f"Failed to page Flipper: {e}"


@mcp.tool()
async def vibrate(
    pattern: Literal["short", "long", "urgent"] = "short"
) -> str:
    """
    Vibrate the Flipper Zero without displaying a message.

    Args:
        pattern: Vibration pattern - short (default), long, or urgent

    Returns:
        Status message indicating success or failure
    """
    payload = f"VIBRATE:{pattern}"

    try:
        await send_to_flipper(payload)
        return f"Flipper vibrated (pattern={pattern})"
    except Exception as e:
        return f"Failed to vibrate Flipper: {e}"


if __name__ == "__main__":
    mcp.run()
