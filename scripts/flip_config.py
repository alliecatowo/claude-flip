"""Shared configuration for claude-flip scripts.

The Flipper's BLE MAC address is never hardcoded. Resolution order:
  1. CLAUDE_FLIP_MAC environment variable
  2. FLIPPER_ADDRESS environment variable (legacy name)
  3. "address" key in ~/.config/claude-flip/config.json
"""

import json
import os
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "claude-flip" / "config.json"

_HELP = (
    "claude-flip: Flipper BLE MAC address is not configured.\n"
    "Set CLAUDE_FLIP_MAC (e.g. export CLAUDE_FLIP_MAC=AA:BB:CC:DD:EE:FF)\n"
    f"or add {{\"address\": \"AA:BB:CC:DD:EE:FF\"}} to {CONFIG_PATH}.\n"
    "Find the MAC with: bluetoothctl devices (after pairing) or the README."
)


def get_flipper_address(required: bool = True):
    """Return the configured Flipper MAC, or exit with a clear error."""
    addr = os.environ.get("CLAUDE_FLIP_MAC") or os.environ.get("FLIPPER_ADDRESS")
    if not addr:
        try:
            addr = json.loads(CONFIG_PATH.read_text()).get("address")
        except (OSError, ValueError, AttributeError):
            addr = None
    if not addr and required:
        print(_HELP, file=sys.stderr)
        sys.exit(1)  # non-blocking: exit 2 would deny/block in hooks
    return addr
