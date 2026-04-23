"""
GPS Reader — Mock Coordinates or GPSD Integration

Provides location data for LoRa alert payloads.
Defaults to mock coordinates for simulation / demo mode.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GPSPosition:
    """GPS fix with latitude, longitude, and validity flag."""
    latitude: float
    longitude: float
    valid: bool = True

    @property
    def lat_microdeg(self) -> int:
        """Latitude as integer microdegrees (for compact payload encoding)."""
        return int(self.latitude * 1_000_000)

    @property
    def lon_microdeg(self) -> int:
        """Longitude as integer microdegrees (for compact payload encoding)."""
        return int(self.longitude * 1_000_000)


class GPSReader:
    """
    GPS position provider.

    In simulation mode, returns fixed mock coordinates.
    On real hardware, can connect to gpsd for live GPS data.
    """

    def __init__(
        self,
        use_gpsd: bool = False,
        mock_latitude: float = -1.948975,
        mock_longitude: float = 34.786740,
    ):
        self.use_gpsd = use_gpsd
        self._mock_position = GPSPosition(
            latitude=mock_latitude,
            longitude=mock_longitude,
            valid=True,
        )
        self._gpsd_session = None

        if use_gpsd:
            self._init_gpsd()
        else:
            logger.info(
                f"GPS: Using mock position "
                f"({mock_latitude:.6f}, {mock_longitude:.6f})"
            )

    def _init_gpsd(self):
        """Initialize GPSD connection (Linux only)."""
        try:
            import gps as gpsd_module
            self._gpsd_session = gpsd_module.gps(mode=gpsd_module.WATCH_ENABLE)
            logger.info("GPS: Connected to gpsd")
        except ImportError:
            logger.warning(
                "GPS: gpsd module not available. Falling back to mock."
            )
            self.use_gpsd = False
        except Exception as e:
            logger.warning(f"GPS: Could not connect to gpsd: {e}. Using mock.")
            self.use_gpsd = False

    def get_position(self) -> GPSPosition:
        """
        Get the current GPS position.

        Returns:
            GPSPosition with coordinates and validity flag.
        """
        if not self.use_gpsd:
            return self._mock_position

        try:
            report = self._gpsd_session.next()
            if report.get("class") == "TPV":
                lat = report.get("lat", 0.0)
                lon = report.get("lon", 0.0)
                if lat != 0.0 and lon != 0.0:
                    return GPSPosition(
                        latitude=lat,
                        longitude=lon,
                        valid=True,
                    )
        except StopIteration:
            pass
        except Exception as e:
            logger.warning(f"GPS read error: {e}")

        return GPSPosition(
            latitude=self._mock_position.latitude,
            longitude=self._mock_position.longitude,
            valid=False,
        )
