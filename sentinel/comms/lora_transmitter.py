"""
LoRa Transmitter — Serial UART Driver with AT Commands

Communicates with a LoRa module (Dragino, RAK, Adafruit) via serial
UART using AT commands. Includes retry logic and simulation mode.
"""

import time
import logging
from typing import Optional

from sentinel.comms.payload import to_hex_string

logger = logging.getLogger(__name__)


class LoRaTransmitter:
    """
    LoRaWAN transmitter via serial UART AT commands.

    In simulation mode, logs payloads to console instead of
    writing to a serial port — enabling development on any machine.
    """

    def __init__(
        self,
        serial_port: str = "/dev/ttyS0",
        baud_rate: int = 9600,
        fport: int = 2,
        retry_count: int = 3,
        retry_delay_sec: float = 2.0,
        simulation_mode: bool = True,
    ):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.fport = fport
        self.retry_count = retry_count
        self.retry_delay_sec = retry_delay_sec
        self.simulation_mode = simulation_mode

        self._serial = None
        self._tx_count = 0
        self._tx_failures = 0

        if not simulation_mode:
            self._open_serial()
        else:
            logger.info("LoRa TX: Running in SIMULATION mode")

    def _open_serial(self):
        """Open the serial port connection."""
        try:
            import serial
            self._serial = serial.Serial(
                port=self.serial_port,
                baudrate=self.baud_rate,
                timeout=5,
            )
            logger.info(
                f"LoRa TX: Serial opened on {self.serial_port} "
                f"@ {self.baud_rate} baud"
            )
        except ImportError:
            logger.error("pyserial not installed. pip install pyserial")
            self.simulation_mode = True
        except Exception as e:
            logger.error(
                f"LoRa TX: Failed to open {self.serial_port}: {e}. "
                f"Falling back to simulation mode."
            )
            self.simulation_mode = True

    def _send_at_command(self, command: str) -> str:
        """Send an AT command and read the response."""
        if self._serial is None:
            return "ERROR: No serial connection"

        try:
            self._serial.write(f"{command}\r\n".encode("utf-8"))
            time.sleep(0.5)

            response = ""
            while self._serial.in_waiting:
                response += self._serial.read(
                    self._serial.in_waiting
                ).decode("utf-8", errors="replace")

            return response.strip()
        except Exception as e:
            logger.error(f"LoRa TX: AT command error: {e}")
            return f"ERROR: {e}"

    def transmit(self, payload_bytes: bytes) -> bool:
        """
        Transmit a binary payload over LoRaWAN.

        Args:
            payload_bytes: Binary payload to transmit.

        Returns:
            True if transmission was successful (or simulated).
        """
        hex_payload = to_hex_string(payload_bytes)
        byte_len = len(payload_bytes)

        if self.simulation_mode:
            self._tx_count += 1
            logger.info(
                f"📡 [SIM] LoRa TX #{self._tx_count}: "
                f"{byte_len} bytes | {hex_payload}"
            )
            return True

        # Real transmission with retry
        command = (
            f"AT+SEND=0,{self.fport},{byte_len},{hex_payload}"
        )

        for attempt in range(1, self.retry_count + 1):
            logger.info(
                f"📡 LoRa TX attempt {attempt}/{self.retry_count}: "
                f"{byte_len} bytes"
            )

            response = self._send_at_command(command)

            if "OK" in response.upper() or "DONE" in response.upper():
                self._tx_count += 1
                logger.info(f"LoRa TX success: {response}")
                return True

            logger.warning(
                f"LoRa TX attempt {attempt} failed: {response}"
            )

            if attempt < self.retry_count:
                time.sleep(self.retry_delay_sec)

        self._tx_failures += 1
        logger.error(
            f"LoRa TX FAILED after {self.retry_count} attempts. "
            f"Total failures: {self._tx_failures}"
        )
        return False

    def close(self):
        """Close the serial port."""
        if self._serial is not None:
            try:
                self._serial.close()
                logger.info("LoRa TX: Serial port closed")
            except Exception:
                pass
            self._serial = None

    @property
    def stats(self) -> dict:
        return {
            "transmissions": self._tx_count,
            "failures": self._tx_failures,
            "simulation_mode": self.simulation_mode,
        }
