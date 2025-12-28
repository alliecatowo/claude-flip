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


DEBUG_MODE = os.environ.get("FLIPPER_DEBUG", "").lower() in ("1", "true", "yes")


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


def get_rule_pattern(tool_name: str, tool_input: dict) -> str:
    """Extract a permission pattern for this tool invocation."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Get first word of command as pattern
        first_word = cmd.split()[0] if cmd.split() else "*"
        return f"{first_word}:*"
    elif tool_name in ("Edit", "Write", "Read"):
        file_path = tool_input.get("file_path", "")
        # Get directory pattern
        if "/" in file_path:
            dir_path = "/".join(file_path.split("/")[:-1])
            return f"{dir_path}/**"
        return "*"
    return "*"


def save_permission_rule(tool_name: str, pattern: str, allow: bool = True):
    """Save a permission rule to .claude/settings.local.json"""
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

        # Build rule string
        rule = f"{tool_name}({pattern})"

        # Add rule if not already present
        if rule not in settings["permissions"][key]:
            settings["permissions"][key].append(rule)
            log_debug(f"Saved rule: {rule}")

            # Write back
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)

        return True
    except Exception as e:
        log_debug(f"Failed to save rule: {e}")
        return False


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

    # Assess risk level
    risk = assess_risk(tool_name, tool_input)

    # Build display message based on tool type
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Show first 45 chars of command (leave room for risk)
        display_msg = f"[{risk}] {cmd[:45]}"
    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        display_msg = f"[{risk}] Edit: {filename}"
    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        display_msg = f"[{risk}] Write: {filename}"
    elif tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        display_msg = f"[{risk}] Read: {filename}"
    else:
        display_msg = f"[{risk}] {tool_name}?"

    # Truncate if too long for Flipper display
    display_msg = display_msg[:60]
    log_debug(f"Display: {display_msg}")

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

        if response == "Y":
            # Allow once
            output = json.dumps(make_response("allow"))
            log_debug(f"Output: {output}")
            print(output)
            sys.exit(0)
        elif response == "A":
            # Allow always - save rule to settings
            pattern = get_rule_pattern(tool_name, tool_input)
            save_permission_rule(tool_name, pattern, allow=True)
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
            # Deny always - save rule to settings
            pattern = get_rule_pattern(tool_name, tool_input)
            save_permission_rule(tool_name, pattern, allow=False)
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
