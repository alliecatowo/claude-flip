#!/usr/bin/env python3
"""
Disable Flipper Zero permission routing by deactivating hooks.json.
"""

import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS_DIR = os.path.join(PLUGIN_ROOT, "hooks")
HOOKS_FILE = os.path.join(HOOKS_DIR, "hooks.json")
HOOKS_DISABLED = os.path.join(HOOKS_DIR, "hooks.json.disabled")


def main():
    # Check if already disabled
    if not os.path.exists(HOOKS_FILE):
        if os.path.exists(HOOKS_DISABLED):
            print("Flipper permission routing is already DISABLED")
            return 0
        else:
            print("ERROR: No hooks configuration found")
            return 1

    # Disable by renaming
    os.rename(HOOKS_FILE, HOOKS_DISABLED)
    print("Flipper permission routing DISABLED")
    print("  Permission requests will use normal Claude Code prompts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
