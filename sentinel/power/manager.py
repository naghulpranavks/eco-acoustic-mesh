"""
Power Manager — Thermal Monitoring & Adaptive Sleep

Manages CPU temperature, inference throttling, and power-efficient
sleep scheduling for solar-powered edge deployment.
"""

import time
import logging
import platform
from typing import Optional

logger = logging.getLogger(__name__)


class PowerManager:
    """
    Monitors system thermals and manages power-efficient sleep intervals.

    On Linux (Pi/Jetson), reads real CPU temperature from sysfs.
    On Windows, uses psutil or returns mock values for development.
    """

    def __init__(
        self,
        thermal_limit_c: int = 75,
        base_sleep_sec: float = 2.0,
        heartbeat_interval_sec: float = 300.0,
        adaptive_sleep: bool = True,
    ):
        self.thermal_limit_c = thermal_limit_c
        self.base_sleep_sec = base_sleep_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.adaptive_sleep = adaptive_sleep

        self._last_heartbeat = time.time()
        self._consecutive_ambient = 0  # Tracks quiet periods
        self._is_linux = platform.system() == "Linux"
        self._battery_pct = 100  # Mock battery level

        logger.info(
            f"Power manager initialized: thermal_limit={thermal_limit_c}°C, "
            f"base_sleep={base_sleep_sec}s, adaptive={adaptive_sleep}"
        )

    def get_cpu_temp(self) -> float:
        """
        Read CPU temperature in Celsius.

        Returns:
            CPU temperature. Returns 45.0 on unsupported platforms.
        """
        # Linux: Read from thermal zone sysfs
        if self._is_linux:
            try:
                with open(
                    "/sys/class/thermal/thermal_zone0/temp", "r"
                ) as f:
                    return float(f.read().strip()) / 1000.0
            except (FileNotFoundError, ValueError, PermissionError):
                pass

        # Fallback: try psutil
        try:
            import psutil
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        return entries[0].current
        except (ImportError, AttributeError):
            pass

        # Development fallback
        return 45.0

    def get_battery_pct(self) -> int:
        """
        Read battery percentage.

        Returns:
            Battery percentage (0-100). Returns mock value if unavailable.
        """
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is not None:
                return int(battery.percent)
        except (ImportError, AttributeError):
            pass

        return self._battery_pct

    def is_overheating(self) -> bool:
        """Check if CPU temperature exceeds the thermal limit."""
        temp = self.get_cpu_temp()
        if temp >= self.thermal_limit_c:
            logger.warning(
                f"🌡️ THERMAL WARNING: {temp:.1f}°C >= {self.thermal_limit_c}°C"
            )
            return True
        return False

    def get_sleep_interval(self) -> float:
        """
        Calculate the adaptive sleep interval based on activity.

        When no threats are detected for extended periods, the sleep
        interval gradually increases to conserve power. Resets on
        threat detection.
        """
        if not self.adaptive_sleep:
            return self.base_sleep_sec

        # Gradually increase sleep up to 4x base when quiet
        if self._consecutive_ambient > 100:
            multiplier = 4.0
        elif self._consecutive_ambient > 50:
            multiplier = 3.0
        elif self._consecutive_ambient > 20:
            multiplier = 2.0
        elif self._consecutive_ambient > 10:
            multiplier = 1.5
        else:
            multiplier = 1.0

        # Extra throttle if overheating
        if self.is_overheating():
            multiplier *= 2.0
            logger.info("Power: Doubling sleep due to thermal throttle")

        interval = self.base_sleep_sec * multiplier
        return interval

    def report_ambient(self):
        """Record that the latest classification was ambient/silent."""
        self._consecutive_ambient += 1

    def report_threat(self):
        """Record that a threat was detected — reset adaptive sleep."""
        self._consecutive_ambient = 0

    def heartbeat_due(self) -> bool:
        """Check if it's time to send a heartbeat payload."""
        elapsed = time.time() - self._last_heartbeat
        return elapsed >= self.heartbeat_interval_sec

    def mark_heartbeat_sent(self):
        """Record that a heartbeat was just sent."""
        self._last_heartbeat = time.time()

    def thermal_cooldown(self):
        """
        Block until CPU temperature drops below the thermal limit.
        Used when temperature is critically high.
        """
        while self.is_overheating():
            temp = self.get_cpu_temp()
            logger.warning(
                f"🌡️ Thermal cooldown: {temp:.1f}°C. "
                f"Sleeping 10s..."
            )
            time.sleep(10)

        logger.info(
            f"Thermal OK: {self.get_cpu_temp():.1f}°C < "
            f"{self.thermal_limit_c}°C"
        )

    @property
    def status(self) -> dict:
        """Current power/thermal status snapshot."""
        return {
            "cpu_temp_c": round(self.get_cpu_temp(), 1),
            "battery_pct": self.get_battery_pct(),
            "is_overheating": self.is_overheating(),
            "sleep_interval_sec": round(self.get_sleep_interval(), 1),
            "consecutive_ambient": self._consecutive_ambient,
        }
