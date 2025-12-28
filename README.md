# Claude Flip - Flipper Zero Claude Code Controller

> Physical hardware approval for AI operations via Flipper Zero 🐬🔐

Route ALL Claude Code permission requests to your Flipper Zero for physical approval via Bluetooth LE. Get buzzed when Claude needs permission, respond with the D-pad.

## Features

- **Hardware Approval**: Every permission request goes to your Flipper Zero
- **D-pad Control**: Physical buttons for Allow/Deny/Remember decisions
- **BLE Serial**: Uses Flipper's BLE Serial Profile for wireless communication
- **Mode Switching**: Cycle through permission modes (Default, Plan, Accept Edits)
- **Stats Tracking**: See request/allow/deny counts on the Flipper display

## Architecture

```
Claude Code Session
        │
        ▼ (PermissionRequest hook)
┌───────────────────┐
│ permission_hook.py│
└───────────────────┘
        │
        ▼ (BLE Serial)
┌───────────────────┐
│ Flipper Zero      │
│ Claude Controller │
│                   │
│  <No  ^Alw  Ok:Y  │
│       vNvr     Y> │
└───────────────────┘
```

## Installation

### Prerequisites

- Python 3.8+
- Flipper Zero with Momentum firmware (or compatible)
- Claude Code CLI
- `bleak` Python package for BLE

### Host Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/claude-flip.git
cd claude-flip

# Install Python dependencies
pip install -r requirements.txt

# Install as Claude Code plugin
claude plugin install . --scope user
```

### Flipper App Setup

```bash
# Using ufbt (recommended)
cd flipper_app
ufbt build
ufbt launch  # Uploads to Flipper via USB

# Or copy the .fap file manually to your Flipper
cp dist/claude_controller.fap /path/to/flipper/apps/Misc/
```

### Configure Flipper Address

Set your Flipper's BLE address (find it in Flipper Settings > Bluetooth):

```bash
export FLIPPER_ADDRESS="80:E1:26:71:4C:EA"  # Your Flipper's address
```

Or add to your shell profile for persistence.

## Usage

1. Launch the "Claude Controller" app on your Flipper
2. Wait for "BLE ready" / connection indicator `[*]`
3. Start a Claude Code session
4. The Flipper will vibrate and display each permission request
5. Use the D-pad to approve/deny

### Button Mapping

| Button | Action | Description |
|--------|--------|-------------|
| ▶ Right / OK | Allow | Approve this request |
| ◀ Left | Deny | Reject this request |
| ▲ Up | Allow Always | Approve and remember for similar commands |
| ▼ Down | Deny Always | Reject and remember for similar commands |
| ● OK (long) | Cycle Mode | Switch between Default/Plan/AcceptEdits |
| ◄ Back | Exit | Close the app |

### Permission Modes

- **Default**: Normal - ask for each permission
- **Plan Only**: Read-only mode (future: auto-deny writes)
- **Accept Edits**: Auto-accept file edits (future: implement)

### Slash Commands

When the plugin is installed, you get these commands:

- `/flipper-status` - Check Flipper connection status
- `/flipper-test` - Send a test message and wait for response
- `/flipper-enable` - Enable Flipper permission routing
- `/flipper-disable` - Disable Flipper permission routing (use normal prompts)

## Display

```
┌────────────────────────────┐
│ Claude Controller     [*]  │  <- [*]=connected, [.]=advertising, [-]=off
├────────────────────────────┤
│ Mode: Default    12/10/2   │  <- mode and stats (requests/allow/deny)
├────────────────────────────┤
│ Bash: npm install          │  <- permission request text
│ some-package               │
├────────────────────────────┤
│ <No ^Alw Ok:Y vNvr     Y>  │  <- button hints
└────────────────────────────┘
```

## Technical Details

### BLE UUIDs

- TX (Flipper → Host): `19ed82ae-ed21-4c9d-4145-228e62fe0000`
- RX (Host → Flipper): `19ed82ae-ed21-4c9d-4145-228e61fe0000`

### Protocol

1. Host sends permission request text (max 60 chars)
2. Flipper sends `ACK` to confirm receipt
3. Flipper vibrates and displays request
4. User presses button
5. Flipper sends response: `Y` (allow), `N` (deny), `A` (allow always), `D` (deny always)

### Response Handling

- `Y` → `{"decision": "allow"}`
- `N` → `{"decision": "deny"}`
- `A` → `{"decision": "allow", "remember_pattern": "cmd *"}`
- `D` → `{"decision": "deny", "remember_pattern": "cmd *"}`

## Development

```bash
# Test the hook manually
echo '{"tool": {"name": "Bash", "params": {"command": "npm install"}}}' | python scripts/permission_hook.py

# Build Flipper app
cd flipper_app
ufbt build

# Check Flipper logs
ufbt cli
> log
```

## Troubleshooting

### "BLE init failed"
- Make sure no other app is using Bluetooth
- Try restarting the Flipper

### "Connection error" on host
- Verify FLIPPER_ADDRESS is correct
- Make sure Claude Controller app is running on Flipper
- Check that Flipper is in range

### No vibration on requests
- Verify the serial profile is connected (display shows `[*]`)
- Check that the permission hook is enabled

## License

MIT
