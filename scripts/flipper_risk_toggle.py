#!/usr/bin/env python3
"""
Toggle risk assessment display on/off.
Stores setting in ~/.config/claude-flip/config.json
"""

import json
import os
import sys

CONFIG_DIR = os.path.expanduser("~/.config/claude-flip")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def main():
    config = load_config()

    # Toggle risk assessment
    current = config.get("show_risk", True)
    config["show_risk"] = not current

    save_config(config)

    if config["show_risk"]:
        print("Risk assessment ENABLED")
        print("  Flipper will show [LOW]/[MED]/[HIGH]/[CRIT] prefix")
    else:
        print("Risk assessment DISABLED")
        print("  Flipper will show commands without risk prefix")


if __name__ == "__main__":
    main()
