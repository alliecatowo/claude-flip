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
    """Send request to Flipper and wait for response.

    Returns:
        str: Response from Flipper - Y/N/A/D or None on timeout
    """
    response = None
    got_ack = False

    def on_notify(sender, data: bytes):
        nonlocal response, got_ack
        text = data.decode().strip()
        if text.startswith("ACK"):
            got_ack = True
        elif text in ("Y", "N", "A", "D"):
            response = text

    async with BleakClient(FLIPPER_ADDRESS, timeout=10) as client:
        await client.start_notify(RX_CHAR_UUID, on_notify)

        # Send the request
        await client.write_gatt_char(
            TX_CHAR_UUID, (request_text + "\n").encode(), response=False
        )

        # Wait for ACK
        for _ in range(5):
            await asyncio.sleep(0.2)
            if got_ack:
                break

        # Wait for user response
        for _ in range(TIMEOUT):
            await asyncio.sleep(1)
            if response:
                break

        await client.stop_notify(RX_CHAR_UUID)

    return response


CONFIG_FILE = os.path.expanduser("~/.config/claude-flip/config.json")


def load_config():
    """Load plugin config."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


# Check both env var and config file for debug mode
_config = load_config()
DEBUG_MODE = (
    os.environ.get("FLIPPER_DEBUG", "").lower() in ("1", "true", "yes") or
    _config.get("debug", False)
)


def log_debug(msg):
    """Write debug info to a file (only if DEBUG_MODE enabled)."""
    if DEBUG_MODE:
        with open("/tmp/flipper_hook_debug.log", "a") as f:
            f.write(f"{msg}\n")


def assess_risk(tool_name: str, tool_input: dict) -> str:
    """Assess risk level of the operation. Returns LOW, MED, HIGH, or CRIT."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "").lower()

        # CRITICAL: Destructive or system-altering commands
        critical_patterns = [
            "rm -rf /", "rm -rf ~", "rm -rf *",
            "mkfs", "dd if=", "> /dev/",
            "chmod 777 /", "chown -R",
            "curl | bash", "curl | sh", "wget | bash",
            ":(){ :|:& };:",  # Fork bomb
        ]
        for pattern in critical_patterns:
            if pattern in cmd:
                return "CRIT"

        # HIGH: Elevated privileges or network operations
        high_patterns = [
            "sudo ", "su -", "doas ",
            "rm -rf", "rm -r",
            "curl ", "wget ",
            "ssh ", "scp ",
            "docker ", "podman ",
            "> /etc/", ">> /etc/",
        ]
        for pattern in high_patterns:
            if pattern in cmd:
                return "HIGH"

        # MEDIUM: File modifications, package installs
        medium_patterns = [
            "npm install", "pip install", "cargo install",
            "git push", "git commit",
            "make install",
            "mv ", "cp ",
        ]
        for pattern in medium_patterns:
            if pattern in cmd:
                return "MED"

        # LOW: Read-only or safe operations
        return "LOW"

    elif tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "").lower()

        # HIGH: System files
        if file_path.startswith("/etc/") or file_path.startswith("/usr/"):
            return "HIGH"

        # MEDIUM: Config files
        if any(p in file_path for p in [".env", "config", "settings", ".json", ".yaml"]):
            return "MED"

        return "LOW"

    elif tool_name == "Read":
        return "LOW"

    return "MED"  # Unknown tools get medium risk


def save_permission_rules(suggestions: list, allow: bool = True):
    """Save permission rules from Claude's suggestions to settings.local.json"""
    settings_path = os.path.expanduser("~/.claude/settings.local.json")

    try:
        # Read existing settings
        if os.path.exists(settings_path):
            with open(settings_path, 'r') as f:
                settings = json.load(f)
        else:
            settings = {}

        # Ensure permissions structure exists
        if "permissions" not in settings:
            settings["permissions"] = {}

        key = "allow" if allow else "deny"
        if key not in settings["permissions"]:
            settings["permissions"][key] = []

        # Extract rules from suggestions
        rules_added = []
        for suggestion in suggestions:
            if suggestion.get("type") == "addRules":
                for rule_def in suggestion.get("rules", []):
                    tool_name = rule_def.get("toolName", "")
                    rule_content = rule_def.get("ruleContent", "")
                    if tool_name and rule_content:
                        rule = f"{tool_name}({rule_content})"
                        if rule not in settings["permissions"][key]:
                            settings["permissions"][key].append(rule)
                            rules_added.append(rule)

        if rules_added:
            log_debug(f"Saved rules: {rules_added}")
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
            return True

        return False
    except Exception as e:
        log_debug(f"Failed to save rules: {e}")
        return False


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

    # Extract relevant info for display (Claude Code format)
    tool_name = request_json.get("tool_name", "Unknown")
    tool_input = request_json.get("tool_input", {})
    permission_suggestions = request_json.get("permission_suggestions", [])

    # Load config for risk display preference
    config = load_config()
    show_risk = config.get("show_risk", True)

    # Assess risk level (if enabled)
    risk_prefix = ""
    if show_risk:
        risk = assess_risk(tool_name, tool_input)
        risk_prefix = f"[{risk}] "

    # Build display message based on tool type
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Show command (adjust length based on risk prefix)
        max_len = 45 if show_risk else 55
        display_msg = f"{risk_prefix}{cmd[:max_len]}"
    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        display_msg = f"{risk_prefix}Edit: {filename}"
    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        display_msg = f"{risk_prefix}Write: {filename}"
    elif tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        display_msg = f"{risk_prefix}Read: {filename}"
    else:
        display_msg = f"{risk_prefix}{tool_name}?"

    # Truncate if too long for Flipper display
    display_msg = display_msg[:60]
    log_debug(f"Display: {display_msg}")

    try:
        response = asyncio.run(send_permission_request(display_msg))
        log_debug(f"Flipper response: {response}")

        if response == "Y":
            # Allow once
            output = json.dumps(make_response("allow"))
            log_debug(f"Output: {output}")
            print(output)
            sys.exit(0)
        elif response == "A":
            # Allow always - save rules from Claude's suggestions
            save_permission_rules(permission_suggestions, allow=True)
            output = json.dumps(make_response("allow"))
            log_debug(f"Output (always): {output}")
            print(output)
            sys.exit(0)
        elif response == "N":
            # Deny once
            output = json.dumps(make_response("deny", "Denied via Flipper Zero"))
            log_debug(f"Output: {output}")
            print(output)
            sys.exit(0)
        elif response == "D":
            # Deny always - save rules from Claude's suggestions as deny rules
            save_permission_rules(permission_suggestions, allow=False)
            output = json.dumps(make_response("deny", "Always denied via Flipper Zero"))
            log_debug(f"Output (never): {output}")
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
