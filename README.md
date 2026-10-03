# claude-flip

Approve or deny Claude Code permission requests with the physical D-pad of a Flipper Zero.

When Claude Code wants to run a command or edit a file, your Flipper buzzes and shows the request. Press a button to allow or deny. No keyboard needed.

## Demo

<!-- TODO: add a photo or GIF of the Flipper approving a Bash command (to be recorded by the author). -->

*Photo/GIF coming soon.*

## How it works

```
Claude Code ──PermissionRequest hook──▶ scripts/permission_hook.py
                                              │  Python + bleak
                                              ▼  BLE serial profile
                                     Flipper Zero "Claude Controller" (FAP)
                                       vibrates, shows "[RISK] Bash: ..."
                                              │  D-pad press
                                              ▼
                      hook prints allow/deny decision JSON back to Claude Code
```

Three pieces:

1. **Flipper app (C, FAP)**: `flipper_app/claude_controller.c` uses the Flipper BLE serial profile, shows the request, vibrates, and sends back a one-letter decision. It also tracks request/allow/deny counts.
2. **Host bridge (Python, bleak)**: `scripts/permission_hook.py` formats a `[LOW|MED|HIGH|CRIT]` risk-scored summary (max 60 chars), sends it over BLE, waits for the Flipper's `ACK`, then waits up to 5 minutes for a button press. It retries flaky BLE connections.
3. **Claude Code plugin**: `hooks/hooks.json` registers the script as a `PermissionRequest` hook and returns the `hookSpecificOutput` decision JSON that Claude Code expects. Slash commands wrap small helper scripts.

Also included: `flipper_app_pager/` (a second, simpler Flipper app that just displays and vibrates for notifications) and `scripts/pager_mcp.py` (an MCP server that lets Claude send pages to it). Both are experimental. Hard-won BLE notes are in [docs/BLE_LESSONS_LEARNED.md](docs/BLE_LESSONS_LEARNED.md).

## Setup

Requirements: Python 3.8+, Claude Code, a Flipper Zero (developed against Momentum firmware), a Bluetooth adapter on the host, and [`ufbt`](https://github.com/flipperdevices/flipperzero-ufbt) to build the app.

```bash
git clone https://github.com/alliecatowo/claude-flip.git
cd claude-flip
pip install -r requirements.txt

# Build and launch the Flipper app (Flipper connected over USB)
cd flipper_app && ufbt launch && cd ..

# Install as a Claude Code plugin
claude plugin install . --scope user
```

### Configure your Flipper's MAC address

The hook needs your Flipper's BLE MAC address. It is never hardcoded; set it with an environment variable:

```bash
export CLAUDE_FLIP_MAC="AA:BB:CC:DD:EE:FF"   # replace with your Flipper's address
```

or in `~/.config/claude-flip/config.json`:

```json
{ "address": "AA:BB:CC:DD:EE:FF" }
```

If it is unset, the scripts exit with a clear error (the legacy `FLIPPER_ADDRESS` variable is also honored).

To find the address: start the Claude Controller app on the Flipper, pair it with your host, then run `bluetoothctl devices` (Linux) or look at the Flipper's name in your OS Bluetooth settings (macOS: System Information > Bluetooth). Running `python scripts/flipper_status.py` after setting the variable confirms the connection.

## Usage

1. Launch "Claude Controller" on the Flipper and wait for the connected indicator `[*]`.
2. Start a Claude Code session.
3. The Flipper vibrates for each permission request. Press a button:

| Button | Action |
|--------|--------|
| Right / OK | Allow |
| Left | Deny |
| Up | Allow always (remember similar commands) |
| Down | Deny always |
| Back | Exit the app |

Slash commands: `/flipper-status`, `/flipper-test`, `/flipper-enable`, `/flipper-disable`, `/flipper-risk` (toggle risk labels on the display).

## Security notes

- The hook trusts whatever answers over the paired BLE link. Security relies on Flipper bonding/pairing with your host; do not leave the app running in a place where untrusted devices can pair.
- If the Flipper is unreachable or the address is unset, the hook fails with an error rather than approving anything.
- Only `PermissionRequest` events are routed; this is a convenience gate, not a sandbox.

## Status

Early project. The core approve/deny loop works; the "mode switching" idea was removed. Hardware smoke tests with a real Flipper are still manual: the probes live in `tests/hardware/` (they need a Flipper and the MAC configured) and are never collected by pytest.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest        # risk assessment, rule saving, hook decisions, BLE retry logic (no hardware needed)
```

CI runs the same commands on every push and pull request. Debug logging (`FLIPPER_DEBUG=1` or `"debug": true` in the config file) writes to `~/.local/state/claude-flip/hook_debug.log` (mode 0600), never to `/tmp`.

## License

[MIT](LICENSE)
