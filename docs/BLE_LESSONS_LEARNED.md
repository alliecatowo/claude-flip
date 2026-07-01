# Bluetooth LE Lessons Learned

Notes from building claude-flip - a BLE Serial communication system between a Linux host and Flipper Zero.

## Overview

This project uses Flipper Zero's BLE Serial Profile to send permission requests from a Python script on Linux and receive button press responses from the Flipper.

## Key Components

### Flipper Zero Side (C)

**BLE Serial Profile Setup:**
```c
#include <bt/bt_service/bt.h>
#include <profiles/serial_profile.h>

// Start serial profile
Bt* bt = furi_record_open(RECORD_BT);
FuriHalBleProfileBase* serial_profile = bt_profile_start(bt, ble_profile_serial, NULL);

// Set callback for incoming data
ble_profile_serial_set_event_callback(serial_profile, 128, serial_callback, app);

// Send data
ble_profile_serial_tx(serial_profile, (uint8_t*)"ACK\n", 4);
```

**Important:** After BT connection, re-set the callback with a small delay:
```c
static void bt_status_callback(BtStatus status, void* context) {
    if(status == BtStatusConnected && app->serial_profile) {
        furi_delay_ms(100);  // Critical: wait before setting callback
        ble_profile_serial_set_event_callback(app->serial_profile, 128, serial_callback, app);
    }
}
```

### Python Side (bleak library)

**Basic Connection:**
```python
from bleak import BleakClient, BleakScanner

# Flipper's BLE Serial UUIDs (standard for Flipper serial profile)
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # Write to Flipper
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Read from Flipper

FLIPPER_ADDRESS = "80:E1:26:71:4C:EA"  # Your Flipper's BLE MAC

async with BleakClient(FLIPPER_ADDRESS, timeout=10) as client:
    # Subscribe to notifications (receive data from Flipper)
    await client.start_notify(RX_CHAR_UUID, callback)

    # Send data to Flipper
    await client.write_gatt_char(TX_CHAR_UUID, b"Hello\n", response=False)
```

## Lessons Learned

### 1. BlueZ (Linux) is Flaky

The Linux Bluetooth stack (BlueZ) has caching issues that cause intermittent connection failures:

- **Symptom:** "Device not found" errors even when device is advertising
- **Cause:** BlueZ caches device info and sometimes fails to update

**Solution: Retry with Scanner Refresh**
```python
async def connect_with_retry(address, max_retries=3):
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                # Scan refreshes BlueZ cache
                await BleakScanner.discover(timeout=1)

            async with BleakClient(address, timeout=10) as client:
                return client
        except Exception:
            continue
    raise Exception("Connection failed after retries")
```

### 2. Connection Timeout Matters

- **Too short (3s):** Frequent failures, especially on retry
- **Too long (30s):** Slow failure detection
- **Sweet spot: 10 seconds** - reliable without being too slow

### 3. Back-to-Back Connections are Problematic

If you disconnect and immediately try to reconnect (e.g., from a different process), it often fails.

**Why:** BlueZ needs time to fully process disconnection before accepting new connection.

**Workarounds:**
- Add delay between disconnect and reconnect (500ms-1s)
- Use a daemon with persistent connection
- Scan before reconnecting to refresh cache

### 4. Multiple Processes = Multiple Problems

Each Python process gets its own BLE connection. You cannot share a connection between processes.

**If you need multiple scripts to communicate with one device:**
- Use a daemon/service that maintains the connection
- Other scripts communicate with daemon via IPC (socket, pipe, etc.)
- Daemon forwards messages over BLE

### 5. Flipper Serial Profile Specifics

- **Buffer size:** 128 bytes typical (set in callback registration)
- **Line endings:** Use `\n` for message framing
- **Bidirectional:** Both sides can send/receive anytime
- **UUIDs are standard:** Same for all Flipper Zeros using serial profile

### 6. Notification Callback Pattern

```python
response = None

def on_notify(sender, data: bytes):
    nonlocal response
    text = data.decode().strip()
    response = text

await client.start_notify(RX_CHAR_UUID, on_notify)

# Wait for response
for _ in range(timeout_seconds):
    await asyncio.sleep(1)
    if response:
        break

await client.stop_notify(RX_CHAR_UUID)
```

### 7. Error Handling

Always handle BLE errors gracefully - connections WILL fail:

```python
try:
    async with BleakClient(address, timeout=10) as client:
        # ... do stuff
except BleakDeviceNotFoundError:
    # Device not advertising or out of range
except BleakError:
    # General BLE error
except asyncio.TimeoutError:
    # Connection or operation timed out
```

## Finding Your Flipper's Address

```python
from bleak import BleakScanner

async def scan():
    devices = await BleakScanner.discover(timeout=5)
    for d in devices:
        print(f"{d.address}: {d.name}")
        # Flipper shows as "flip_XXXXXXX"

asyncio.run(scan())
```

Or on Flipper: Settings → Bluetooth → show MAC address

## Architecture Recommendations

### For Simple Request/Response
Single script connects, sends, waits for response, disconnects. Works well but has latency.

### For Frequent Communication
Use a background daemon:
```
┌─────────────┐      IPC       ┌──────────┐      BLE      ┌─────────┐
│ Your Script │ ◄──────────► │  Daemon   │ ◄───────────► │ Flipper │
└─────────────┘               └──────────┘               └─────────┘
                              (persistent connection)
```

### For Hooks/Plugins
Be aware that hooks may run as separate processes. If you need a hook to communicate with BLE:
- Keep hook simple and fast
- Accept that BLE connections from hooks may fail
- Consider fallback behavior

## Common Gotchas

1. **Flipper app must be running** - BLE serial profile only active when your app runs
2. **Only one connection** - Flipper's serial profile accepts one client at a time
3. **UTF-8 encoding** - Always encode/decode strings properly
4. **Newlines** - Strip `\n` and `\r` when parsing received data
5. **Context switches** - If Flipper app loses focus, BLE may disconnect

## Dependencies

```bash
pip install bleak  # Cross-platform BLE library
```

## Testing Connection

Quick test script:
```python
import asyncio
from bleak import BleakClient

TX = "19ed82ae-ed21-4c9d-4145-228e62fe0000"
RX = "19ed82ae-ed21-4c9d-4145-228e61fe0000"
ADDR = "YOUR_FLIPPER_ADDRESS"

async def test():
    def on_rx(sender, data):
        print(f"Received: {data.decode().strip()}")

    async with BleakClient(ADDR, timeout=10) as client:
        print("Connected!")
        await client.start_notify(RX, on_rx)
        await client.write_gatt_char(TX, b"PING\n", response=False)
        await asyncio.sleep(5)  # Wait for response
        await client.stop_notify(RX)

asyncio.run(test())
```
