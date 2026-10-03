#!/usr/bin/env python3
"""
Claude Code permission hook - routes requests to Flipper Zero.
Reads JSON from stdin, sends to Flipper via BLE, returns decision.
"""

import asyncio
import json
import os
import re
import shlex
import sys

# Add this directory to the path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flip_config import append_private_log, get_flipper_address
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

# Flipper BLE Serial UUIDs
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"

# Flipper address (CLAUDE_FLIP_MAC env or ~/.config/claude-flip/config.json)
FLIPPER_ADDRESS = get_flipper_address()

TIMEOUT = 300  # 5 minutes max wait for user response


async def send_permission_request(request_text: str, max_retries: int = 3) -> str:
    """Send request to Flipper and wait for response.

    Returns:
        str: Response from Flipper - Y/N/A/D or None on timeout
    """
    response = None
    got_ack = False

    def on_notify(sender: BleakGATTCharacteristic, data: bytearray):
        nonlocal response, got_ack
        text = data.decode().strip()
        if text.startswith("ACK"):
            got_ack = True
        elif text in ("Y", "N", "A", "D"):
            response = text

    # Retry loop for flaky BLE connections
    last_error = None
    for attempt in range(max_retries):
        try:
            # Quick scan to wake up BlueZ cache on retry
            if attempt > 0:
                await BleakScanner.discover(timeout=1)

            async with BleakClient(FLIPPER_ADDRESS, timeout=10) as client:
                await client.start_notify(RX_CHAR_UUID, on_notify)
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

            return response  # Success, exit retry loop

        except Exception as e:
            last_error = e
            continue  # Try again

    # All retries failed
    raise last_error if last_error else Exception("BLE connection failed")


CONFIG_FILE = os.path.expanduser("~/.config/claude-flip/config.json")


def load_config():
    """Load plugin config."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


# Check both env var and config file for debug mode
_config = load_config()
DEBUG_MODE = (
    os.environ.get("FLIPPER_DEBUG", "").lower() in ("1", "true", "yes") or
    _config.get("debug", False)
)


def log_debug(msg):
    """Write debug info to a private log file (only if DEBUG_MODE enabled).

    The file is ~/.local/state/claude-flip/hook_debug.log (mode 0600): it records the commands
    Claude Code asks about, so it must not sit in a shared directory like /tmp.
    """
    if DEBUG_MODE:
        append_private_log("hook_debug.log", str(msg))


_PIPELINE_OPERATORS = {"|", "|&"}
_COMMAND_SEPARATORS = {"||", "&&", ";", ";;", "&", "(", ")", "\n"}
_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "ash"}
_FETCHERS = {"curl", "wget"}
_HARMLESS_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/zero"}
_DANGEROUS_RM_TARGETS = {"/", "/*", "~", "~/", "~/*", "*", "$HOME", "$HOME/", "$HOME/*", "${HOME}"}
_PRIVILEGE_COMMANDS = {"sudo", "su", "doas"}
_WRAPPERS = {"sudo", "doas", "command", "exec", "nohup", "time", "env", "nice", "xargs"}
_MEDIUM_SUBCOMMANDS = {
    "npm": {"install", "i"}, "pip": {"install"}, "pip3": {"install"}, "cargo": {"install"},
    "git": {"push", "commit"}, "make": {"install"},
}


_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _tokenize(cmd: str) -> list:
    """Split a shell command into tokens with operators (| && ; > ...) as separate tokens."""
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to whitespace splitting
        return cmd.split()


def _parse_pipelines(cmd: str):
    """Return pipelines: lists of (argv, redirect_targets) joined by | within a pipeline.

    Pipelines are separated by && || ; & and newlines. Leading VAR=value assignments are dropped.
    """
    pipelines, pipeline, argv, redirects = [], [], [], []
    tokens = _tokenize(cmd)
    i = 0

    def end_command():
        nonlocal argv, redirects
        while argv and _ASSIGNMENT.match(argv[0]):
            argv = argv[1:]
        if argv or redirects:
            pipeline.append((argv, redirects))
        argv, redirects = [], []

    def end_pipeline():
        nonlocal pipeline
        end_command()
        if pipeline:
            pipelines.append(pipeline)
        pipeline = []

    while i < len(tokens):
        tok = tokens[i]
        if tok in _PIPELINE_OPERATORS:
            end_command()
        elif tok in _COMMAND_SEPARATORS:
            end_pipeline()
        elif tok in _REDIRECTS or (tok[:1].isdigit() and tok[1:] in _REDIRECTS):
            if i + 1 < len(tokens):
                redirects.append(tokens[i + 1])
                i += 1
        else:
            argv.append(tok)
        i += 1
    end_pipeline()
    return pipelines


def _strip_wrappers(argv: list) -> list:
    """Drop sudo/env/... prefixes (and their flags) so the real command is argv[0]."""
    argv = list(argv)
    while argv and os.path.basename(argv[0]) in _WRAPPERS:
        argv.pop(0)
        while argv and (argv[0].startswith("-") or _ASSIGNMENT.match(argv[0])):
            argv.pop(0)
    return argv


def _is_recursive_rm(argv: list) -> bool:
    flags = [a for a in argv[1:] if a.startswith("-")]
    return any(
        a in ("--recursive", "-R", "-r") or (not a.startswith("--") and ("r" in a[1:] or "R" in a[1:]))
        for a in flags
    )


def _assess_bash(raw_cmd: str) -> str:
    cmd = raw_cmd.lower()
    if ":(){ :|:& };:" in cmd or ":(){:|:&};:" in cmd:
        return "CRIT"

    level = "LOW"
    rank = {"LOW": 0, "MED": 1, "HIGH": 2, "CRIT": 3}

    def raise_to(new):
        nonlocal level
        if rank[new] > rank[level]:
            level = new

    for pipeline in _parse_pipelines(raw_cmd):
        commands = []  # (name, argv_without_wrappers, had_privilege_wrapper)
        for argv, redirects in pipeline:
            real = _strip_wrappers(argv)
            privileged = any(os.path.basename(a) in _PRIVILEGE_COMMANDS for a in argv[: len(argv) - len(real)])
            name = os.path.basename(real[0]).lower() if real else ""
            commands.append((name, real, privileged))

            for target in redirects:
                if target.startswith("/dev/") and target not in _HARMLESS_DEVICES and not target.startswith("/dev/fd/"):
                    raise_to("CRIT")
                elif target.startswith("/etc/"):
                    raise_to("HIGH")

        # Anything fetched from the network and piped into a shell
        seen_fetcher = False
        for name, _real, _priv in commands:
            if name in _FETCHERS:
                seen_fetcher = True
            elif seen_fetcher and name in _SHELLS:
                raise_to("CRIT")

        for name, real, privileged in commands:
            if not name:
                continue
            if privileged or name in _PRIVILEGE_COMMANDS:
                raise_to("HIGH")
            if name.startswith("mkfs"):
                raise_to("CRIT")
            elif name == "dd" and any(a.startswith("if=") for a in real[1:]):
                raise_to("CRIT")
            elif name == "chown" and any(a in ("-R", "--recursive") for a in real[1:]):
                raise_to("CRIT")
            elif name == "chmod" and "777" in real[1:] and any(a in ("/", "/*") for a in real[1:]):
                raise_to("CRIT")
            elif name == "rm" and _is_recursive_rm(real):
                targets = [a for a in real[1:] if not a.startswith("-")]
                raise_to("CRIT" if any(t in _DANGEROUS_RM_TARGETS for t in targets) else "HIGH")
            elif name in _FETCHERS | {"ssh", "scp", "docker", "podman"}:
                raise_to("HIGH")
            elif name in _MEDIUM_SUBCOMMANDS and any(a in _MEDIUM_SUBCOMMANDS[name] for a in real[1:3]):
                raise_to("MED")
            elif name in ("mv", "cp"):
                raise_to("MED")

    return level


def assess_risk(tool_name: str, tool_input: dict) -> str:
    """Assess risk level of the operation. Returns LOW, MED, HIGH, or CRIT.

    Bash commands are parsed with shlex into pipelines, so `curl x | bash`, `cat f | sudo tee g`
    and `rm -rf ~` are recognised however they are spaced, while `echo "curl"` and
    `> /dev/null` are not mistaken for dangerous operations.
    """
    if tool_name == "Bash":
        return _assess_bash(tool_input.get("command", ""))

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
