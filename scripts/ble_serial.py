#!/usr/bin/env python3
"""
BLE Serial wrapper that provides a serial.Serial-like interface over BLE.
This allows using flipperzero_protobuf library over Bluetooth.
"""

import asyncio
import threading
from collections import deque
from bleak import BleakClient

# Flipper BLE Serial UUIDs
SERIAL_SERVICE_UUID = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"
TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # Host -> Flipper (write)
RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper -> Host (indicate)


class BleSerial:
    """BLE Serial wrapper that mimics pyserial interface for Flipper Zero."""

    def __init__(self, address: str, debug: bool = False):
        self.address = address
        self.port = f"BLE:{address}"
        self.debug = debug
        self._client: BleakClient = None
        self._rx_buffer = deque()
        self._rx_event = threading.Event()
        self._loop = None
        self._thread = None
        self._connected = False

    def _notification_handler(self, sender, data: bytes):
        """Handle incoming BLE notifications."""
        if self.debug:
            print(f"RX: {data.hex()} ({len(data)} bytes)")
        for b in data:
            self._rx_buffer.append(b)
        self._rx_event.set()

    def _run_loop(self):
        """Run asyncio event loop in background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect(self):
        """Connect to Flipper via BLE."""
        self._client = BleakClient(self.address)
        await self._client.connect()

        # Subscribe to RX characteristic (indications)
        await self._client.start_notify(RX_CHAR_UUID, self._notification_handler)
        self._connected = True

        if self.debug:
            print(f"Connected to {self.address}")

    async def _disconnect(self):
        """Disconnect from Flipper."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(RX_CHAR_UUID)
            except:
                pass
            await self._client.disconnect()
        self._connected = False

    async def _write_async(self, data: bytes):
        """Write data to TX characteristic."""
        if self.debug:
            print(f"TX: {data.hex()} ({len(data)} bytes)")
        await self._client.write_gatt_char(TX_CHAR_UUID, data, response=False)

    def open(self):
        """Open BLE connection (blocking)."""
        # Start event loop in background thread
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Wait for loop to start
        while self._loop is None:
            import time
            time.sleep(0.01)

        # Connect
        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        future.result(timeout=30)

    def close(self):
        """Close BLE connection."""
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)
            future.result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)

    def write(self, data: bytes) -> int:
        """Write data to Flipper."""
        if not self._connected:
            raise IOError("Not connected")

        future = asyncio.run_coroutine_threadsafe(self._write_async(data), self._loop)
        future.result(timeout=10)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        """Read bytes from RX buffer (blocking)."""
        result = bytearray()
        while len(result) < size:
            if self._rx_buffer:
                result.append(self._rx_buffer.popleft())
            else:
                self._rx_event.clear()
                self._rx_event.wait(timeout=30)
        return bytes(result)

    def read_until(self, terminator: bytes = b'\n') -> bytes:
        """Read until terminator is found."""
        result = bytearray()
        while True:
            if self._rx_buffer:
                b = self._rx_buffer.popleft()
                result.append(b)
                if result.endswith(terminator):
                    return bytes(result)
            else:
                self._rx_event.clear()
                self._rx_event.wait(timeout=30)

    def readline(self) -> bytes:
        """Read a line."""
        return self.read_until(b'\n')

    def flushOutput(self):
        """Flush output (no-op for BLE)."""
        pass

    def flushInput(self):
        """Flush input buffer."""
        self._rx_buffer.clear()

    @property
    def timeout(self):
        return None

    @timeout.setter
    def timeout(self, val):
        pass

    @property
    def baudrate(self):
        return 0

    @baudrate.setter
    def baudrate(self, val):
        pass


def create_ble_flipper(address: str, debug: bool = False):
    """Create a FlipperProto instance using BLE transport."""
    from flipperzero_protobuf import FlipperProto
    from flipperzero_protobuf.flipper_base import FlipperProtoBase
    import serial

    # Create BLE serial wrapper
    ble_serial = BleSerial(address, debug=debug)
    ble_serial.open()

    # Create FlipperProto bypassing normal init
    # We manually set up the object since the library expects USB serial
    proto = object.__new__(FlipperProto)
    FlipperProtoBase.__init__.__code__  # just to ensure class is loaded

    # Manually initialize the base class attributes
    proto._debug = 1 if debug else 0
    proto._in_session = False
    proto._command_id = 0
    proto._serial = ble_serial
    proto.device_info = {}
    proto.version = "0.1.0"  # placeholder

    # Import flipper_pb2 for status lookup
    from flipperzero_protobuf.flipperzero_protobuf_compiled import flipper_pb2
    proto.Status_values_by_number = flipper_pb2.DESCRIPTOR.enum_types_by_name[
        "CommandStatus"
    ].values_by_number

    # BLE serial is already an RPC channel (no start_rpc_session needed)
    proto._in_session = True

    return proto, ble_serial


if __name__ == "__main__":
    # Test connection
    FLIPPER_ADDRESS = "80:E1:26:71:4C:EA"

    print(f"Connecting to Flipper at {FLIPPER_ADDRESS}...")
    print("Make sure Claude Controller app is running on Flipper!")
    proto, ble = create_ble_flipper(FLIPPER_ADDRESS, debug=True)

    print("Connected! Testing system ping...")
    try:
        proto.rpc_system_ping()
        print("Ping successful!")
    except Exception as e:
        print(f"Ping failed: {e}")

    # Test storage first
    print("\nTesting storage access...")
    try:
        files = proto.rpc_storage_list("/ext/apps/Tools")
        print(f"   Files: {[f.get('name') for f in files]}")
    except Exception as e:
        print(f"   Storage error: {e}")

    # Check lock status
    print("\nChecking app lock status...")
    try:
        locked = proto.rpc_lock_status()
        print(f"   Locked: {locked}")
    except Exception as e:
        print(f"   Lock check error: {e}")

    # Start app via RPC
    import time
    print("\nStarting Claude Controller via RPC...")
    try:
        proto.rpc_app_start("/ext/apps/Tools/claude_controller.fap", "")
        print("   App started!")
        time.sleep(2)

        print("Sending test data...")
        proto.rpc_app_data_exchange_send(b'hello world')
        print("   Sent!")

        print("Waiting for response...")
        response = proto.rpc_app_data_exchange_recv()
        print(f"   GOT: {response}")

    except Exception as e:
        print(f"   Error: {e}")

    ble.close()
    print("Done!")
