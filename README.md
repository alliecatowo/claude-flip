# Claude Flip - Flipper Zero Claude Code Controller

Route ALL Claude Code permission requests to your Flipper Zero for physical approval. Get buzzed when Claude needs permission, respond with the D-pad.

## Features

- **Hardware Approval**: Every permission request goes to your Flipper Zero
- **D-pad Control**: Left = Deny, Right = Allow, Down = Allow & Remember
- **Risk Assessment**: Different buzzer patterns for LOW/MEDIUM/HIGH/CRITICAL operations
- **Pattern Matching**: Auto-approve trusted patterns (e.g., `npm run *`)
- **Mode Switching**: Cycle through permission modes from the Flipper
- **Dual Connectivity**: USB Serial or Bluetooth LE

## Architecture

```
Claude Code Session
        │
        ▼ (automatic hook)
┌───────────────────┐
│ PermissionRequest │
│ Hook              │
└───────────────────┘
        │
        ▼ (USB/BLE)
┌───────────────────┐
│ Flipper Zero      │
│ ◀DENY    ALLOW▶   │
└───────────────────┘
```

## Installation

### Prerequisites

- Python 3.8+
- Flipper Zero with latest firmware
- Claude Code CLI

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
# Option 1: Using ufbt (recommended)
cd flipper_app
ufbt build
ufbt launch  # Uploads to Flipper via USB

# Option 2: Using fbt with firmware clone
git clone https://github.com/flipperdevices/flipperzero-firmware.git
cp -r flipper_app/ flipperzero-firmware/applications_user/claude_controller/
cd flipperzero-firmware
./fbt launch APPSRC=applications_user/claude_controller
```

## Usage

1. Connect your Flipper Zero via USB or pair via Bluetooth
2. Launch the "Claude Controller" app on your Flipper
3. Start a Claude Code session - the Flipper will intercept all permission requests
4. Use the D-pad to approve/deny operations

### Button Mapping

| Button | Action |
|--------|--------|
| ▶ Right | Allow |
| ◀ Left | Deny |
| ▼ Down | Allow & Remember |
| ▲ Up | Scroll |
| ● OK (long) | Cycle mode |
| ◄ Back | Exit |

### Permission Modes

- **default**: Normal permission checking
- **plan**: Read-only mode (Claude can only analyze)
- **acceptEdits**: Auto-accept file edits

## Configuration

Config file: `~/.config/claude-flip/config.json`

```json
{
  "connection": {
    "type": "auto",
    "serial_port": "/dev/ttyACM0",
    "ble_name": "Flipper",
    "timeout_seconds": 300
  },
  "always_allow": [
    {"tool": "Read", "pattern": "*"},
    {"tool": "Bash", "pattern": "npm run *"}
  ],
  "always_deny": [
    {"tool": "Bash", "pattern": "rm -rf /*"}
  ]
}
```

## Development

```bash
# Run tests
pytest tests/

# Test the hook manually
echo '{"tool_name": "Bash", "tool_input": {"command": "npm install"}}' | python scripts/permission_hook.py
```

## License

MIT
