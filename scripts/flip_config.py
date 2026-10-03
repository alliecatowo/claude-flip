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


def private_log_path(name: str) -> Path:
    """Path of a log file in a private, user-owned directory.

    Logs can contain the commands Claude Code asks permission for, so they must not live
    in a world-readable, predictable location such as /tmp. Uses
    $XDG_STATE_HOME/claude-flip (default ~/.local/state/claude-flip).
    """
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "claude-flip" / name


def append_private_log(name: str, line: str) -> None:
    """Append a line to a private log (dir 0700, file 0600, never follows symlinks).

    Failures are swallowed: logging must never break a permission hook.
    """
    try:
        path = private_log_path(name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
