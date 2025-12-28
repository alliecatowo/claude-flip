#!/usr/bin/env python3
"""
Enable Flipper Zero permission routing by activating hooks.json.
"""

import os
import sys

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS_DIR = os.path.join(PLUGIN_ROOT, "hooks")
HOOKS_FILE = os.path.join(HOOKS_DIR, "hooks.json")
HOOKS_DISABLED = os.path.join(HOOKS_DIR, "hooks.json.disabled")


def main():
    # Check if already enabled
    if os.path.exists(HOOKS_FILE):
        print("Flipper permission routing is already ENABLED")
        print(f"  Hook file: {HOOKS_FILE}")
        return 0

    # Check if disabled file exists
    if os.path.exists(HOOKS_DISABLED):
        os.rename(HOOKS_DISABLED, HOOKS_FILE)
        print("Flipper permission routing ENABLED")
        print("  All permission requests will now route to your Flipper Zero")
        print("  Make sure Claude Controller app is running on your Flipper")
        return 0

    # Neither file exists - something is wrong
    print("ERROR: No hooks configuration found")
    print(f"  Expected: {HOOKS_FILE}")
    print(f"  Or: {HOOKS_DISABLED}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
