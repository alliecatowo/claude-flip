#!/usr/bin/env python3
"""
Flipper Bridge - Communication layer between Claude Code hooks and Flipper Zero.

Supports both Bluetooth LE (primary) and USB Serial (fallback for testing).
"""

import asyncio
import json
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG if os.environ.get('DEBUG') else logging.INFO)
logger = logging.getLogger(__name__)

# BLE Service UUIDs for Flipper Zero Serial Profile
# These are the correct UUIDs from the Flipper firmware
FLIPPER_BLE_SERVICE_UUID = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"
FLIPPER_BLE_TX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # Host -> Flipper (Write)
FLIPPER_BLE_RX_CHAR_UUID = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper -> Host (Notify)


class ConnectionType(Enum):
    USB_SERIAL = "usb"
    BLE = "ble"
    AUTO = "auto"


@dataclass
class FlipperMessage:
    """Message to/from Flipper Zero."""
    type: str  # "permission", "status", "mode", "response", "mode_change"
    id: Optional[str] = None
    tool: Optional[str] = None
    summary: Optional[str] = None
    risk: Optional[str] = None
    action: Optional[str] = None
    pattern: Optional[str] = None
    message: Optional[str] = None
    progress: Optional[int] = None
    current: Optional[str] = None
    mode: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON, excluding None values."""
        data = {k: v for k, v in self.__dict__.items() if v is not None}
        return json.dumps(data) + "\n"

    @classmethod
    def from_json(cls, json_str: str) -> "FlipperMessage":
        """Deserialize from JSON."""
        data = json.loads(json_str.strip())
        return cls(**data)


class FlipperConnection(ABC):
    """Abstract base class for Flipper connections."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection. Returns True on success."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        pass

    @abstractmethod
    async def send(self, message: FlipperMessage) -> None:
        """Send a message to Flipper."""
        pass

    @abstractmethod
    async def receive(self, timeout: float = 300.0) -> Optional[FlipperMessage]:
        """Receive a message from Flipper. Returns None on timeout."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected."""
        pass


class USBSerialConnection(FlipperConnection):
    """USB Serial connection to Flipper Zero."""

    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 230400):
        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self._buffer = b""

    async def connect(self) -> bool:
        try:
            import serial
            self._serial = serial.Serial(
                self.port,
                self.baudrate,
                timeout=0.1,
                write_timeout=1.0
            )
            logger.info(f"Connected to Flipper via USB at {self.port}")
            return True
        except Exception as e:
            logger.error(f"USB Serial connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        if self._serial:
            self._serial.close()
            self._serial = None
            logger.info("USB Serial disconnected")

    async def send(self, message: FlipperMessage) -> None:
        if not self._serial:
            raise ConnectionError("Not connected")
        data = message.to_json().encode('utf-8')
        self._serial.write(data)
        self._serial.flush()
        logger.debug(f"Sent: {message.to_json().strip()}")

    async def receive(self, timeout: float = 300.0) -> Optional[FlipperMessage]:
        if not self._serial:
            raise ConnectionError("Not connected")

        start_time = time.time()
        while time.time() - start_time < timeout:
            # Read available data
            if self._serial.in_waiting:
                self._buffer += self._serial.read(self._serial.in_waiting)

            # Check for complete message (newline-terminated)
            if b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                try:
                    msg = FlipperMessage.from_json(line.decode('utf-8'))
                    logger.debug(f"Received: {line.decode('utf-8')}")
                    return msg
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON received: {line}, error: {e}")
                    continue

            # Small sleep to avoid busy-waiting
            await asyncio.sleep(0.05)

        logger.warning(f"Receive timeout after {timeout}s")
        return None

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open


class BLEConnection(FlipperConnection):
    """Bluetooth LE connection to Flipper Zero."""

    def __init__(self, device_name: str = "Flipper"):
        self.device_name = device_name
        self._client = None
        self._buffer = b""
        self._rx_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self) -> bool:
        try:
            from bleak import BleakClient, BleakScanner

            logger.info(f"Scanning for Flipper Zero ({self.device_name})...")

            # Scan for the Flipper
            device = await BleakScanner.find_device_by_name(
                self.device_name,
                timeout=10.0
            )

            if not device:
                logger.error(f"Flipper Zero '{self.device_name}' not found")
                return False

            logger.info(f"Found Flipper at {device.address}")

            # Connect to the device
            self._client = BleakClient(device.address)
            await self._client.connect()

            # Subscribe to RX characteristic for notifications
            await self._client.start_notify(
                FLIPPER_BLE_RX_CHAR_UUID,
                self._handle_rx_notification
            )

            logger.info("Connected to Flipper via BLE")
            return True

        except ImportError:
            logger.error("bleak library not installed. Run: pip install bleak")
            return False
        except Exception as e:
            logger.error(f"BLE connection failed: {e}")
            return False

    def _handle_rx_notification(self, sender, data: bytes):
        """Handle incoming BLE notifications."""
        self._buffer += data
        # Check for complete messages
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                msg = FlipperMessage.from_json(line.decode('utf-8'))
                logger.debug(f"BLE Received: {line.decode('utf-8')}")
                asyncio.get_event_loop().call_soon_threadsafe(
                    self._rx_queue.put_nowait, msg
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON received via BLE: {line}, error: {e}")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None
            logger.info("BLE disconnected")

    async def send(self, message: FlipperMessage) -> None:
        if not self._client or not self._client.is_connected:
            raise ConnectionError("Not connected")

        data = message.to_json().encode('utf-8')

        # BLE has MTU limits, may need to chunk large messages
        # Flipper typically supports 512 byte MTU after negotiation
        chunk_size = 500
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            await self._client.write_gatt_char(FLIPPER_BLE_TX_CHAR_UUID, chunk)

        logger.debug(f"BLE Sent: {message.to_json().strip()}")

    async def receive(self, timeout: float = 300.0) -> Optional[FlipperMessage]:
        if not self._client or not self._client.is_connected:
            raise ConnectionError("Not connected")

        try:
            msg = await asyncio.wait_for(
                self._rx_queue.get(),
                timeout=timeout
            )
            return msg
        except asyncio.TimeoutError:
            logger.warning(f"BLE receive timeout after {timeout}s")
            return None

    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected


class FlipperBridge:
    """
    Main bridge class that manages connection to Flipper Zero.

    Tries BLE first (primary), falls back to USB Serial (for testing).
    """

    def __init__(
        self,
        connection_type: ConnectionType = ConnectionType.AUTO,
        serial_port: str = "/dev/ttyACM0",
        ble_name: str = "Flipper",
        timeout: float = 300.0
    ):
        self.connection_type = connection_type
        self.serial_port = serial_port
        self.ble_name = ble_name
        self.timeout = timeout
        self._connection: Optional[FlipperConnection] = None

    async def connect(self) -> bool:
        """
        Establish connection to Flipper Zero.

        For AUTO mode: tries BLE first, then USB Serial.
        Returns True if connected, False otherwise.
        """
        if self.connection_type == ConnectionType.BLE:
            self._connection = BLEConnection(self.ble_name)
            return await self._connection.connect()

        elif self.connection_type == ConnectionType.USB_SERIAL:
            self._connection = USBSerialConnection(self.serial_port)
            return await self._connection.connect()

        else:  # AUTO - try BLE first, then USB
            # Try BLE first (primary connection method)
            logger.info("Attempting BLE connection (primary)...")
            ble_conn = BLEConnection(self.ble_name)
            if await ble_conn.connect():
                self._connection = ble_conn
                return True

            # Fall back to USB Serial
            logger.info("BLE failed, trying USB Serial (fallback)...")
            usb_conn = USBSerialConnection(self.serial_port)
            if await usb_conn.connect():
                self._connection = usb_conn
                return True

            logger.error("No connection method succeeded")
            return False

    async def disconnect(self) -> None:
        """Close the connection."""
        if self._connection:
            await self._connection.disconnect()
            self._connection = None

    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._connection is not None and self._connection.is_connected()

    async def send_permission_request(
        self,
        request_id: str,
        tool: str,
        summary: str,
        risk: str
    ) -> Optional[FlipperMessage]:
        """
        Send a permission request and wait for response.

        Returns the response message, or None if timeout/error.
        """
        if not self.is_connected():
            if not await self.connect():
                return None

        message = FlipperMessage(
            type="permission",
            id=request_id,
            tool=tool,
            summary=summary,
            risk=risk
        )

        try:
            await self._connection.send(message)
            response = await self._connection.receive(timeout=self.timeout)
            return response
        except Exception as e:
            logger.error(f"Error sending permission request: {e}")
            return None

    async def send_status(self, message: str, progress: Optional[int] = None) -> None:
        """Send a status update to the Flipper (non-blocking, no response expected)."""
        if not self.is_connected():
            return

        status = FlipperMessage(
            type="status",
            message=message,
            progress=progress
        )

        try:
            await self._connection.send(status)
        except Exception as e:
            logger.warning(f"Failed to send status: {e}")

    async def send_mode_update(self, current_mode: str) -> None:
        """Notify Flipper of current permission mode."""
        if not self.is_connected():
            return

        mode_msg = FlipperMessage(
            type="mode",
            current=current_mode
        )

        try:
            await self._connection.send(mode_msg)
        except Exception as e:
            logger.warning(f"Failed to send mode update: {e}")


# Convenience function for synchronous use in hooks
def send_permission_request_sync(
    request_id: str,
    tool: str,
    summary: str,
    risk: str,
    config: Optional[dict] = None
) -> Optional[dict]:
    """
    Synchronous wrapper for sending permission requests.

    Returns dict with 'action' key ('allow', 'deny', 'allow_remember') or None on failure.
    """
    config = config or {}

    bridge = FlipperBridge(
        connection_type=ConnectionType.AUTO,
        serial_port=config.get('serial_port', '/dev/ttyACM0'),
        ble_name=config.get('ble_name', 'Flipper'),
        timeout=config.get('timeout_seconds', 300)
    )

    async def _async_request():
        try:
            response = await bridge.send_permission_request(
                request_id, tool, summary, risk
            )
            await bridge.disconnect()
            if response:
                return {
                    'action': response.action,
                    'pattern': response.pattern
                }
            return None
        except Exception as e:
            logger.error(f"Permission request failed: {e}")
            await bridge.disconnect()
            return None

    return asyncio.run(_async_request())


if __name__ == "__main__":
    # Quick test
    async def test():
        bridge = FlipperBridge()

        if await bridge.connect():
            print("Connected to Flipper!")

            # Send a test permission request
            response = await bridge.send_permission_request(
                request_id="test123",
                tool="Bash",
                summary="npm install",
                risk="low"
            )

            if response:
                print(f"Response: {response.action}")
            else:
                print("No response received")

            await bridge.disconnect()
        else:
            print("Failed to connect")

    asyncio.run(test())
