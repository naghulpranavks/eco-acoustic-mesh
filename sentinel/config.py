"""
Configuration Loader — YAML to Typed Dataclasses

Loads config.yaml into frozen Python dataclasses for type-safe,
IDE-friendly access across the sentinel system.
"""

import os
import yaml
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Default config path (relative to project root)
_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.yaml",
)


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    buffer_duration_sec: float = 5.0
    chunk_duration_sec: float = 0.5
    silence_threshold_db: float = -40.0
    device_index: Optional[int] = None


@dataclass(frozen=True)
class InferenceConfig:
    model: str = "gemma4:e2b"
    confidence_threshold: float = 0.70
    max_inference_time_sec: float = 15.0
    ollama_host: str = "http://localhost:11434"
    use_minimal_prompt: bool = False


@dataclass(frozen=True)
class LoRaConfig:
    serial_port: str = "/dev/ttyS0"
    baud_rate: int = 9600
    fport: int = 2
    retry_count: int = 3
    retry_delay_sec: float = 2.0


@dataclass(frozen=True)
class PowerConfig:
    thermal_limit_c: int = 75
    sleep_interval_sec: float = 2.0
    heartbeat_interval_sec: float = 300.0
    adaptive_sleep: bool = True


@dataclass(frozen=True)
class GPSConfig:
    use_gpsd: bool = False
    mock_latitude: float = -1.948975
    mock_longitude: float = 34.786740


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: str = "sentinel.log"
    max_bytes: int = 5_242_880
    backup_count: int = 3


@dataclass(frozen=True)
class SentinelConfig:
    node_id: int = 1
    simulation_mode: bool = True


@dataclass(frozen=True)
class AppConfig:
    """Root configuration container."""
    sentinel: SentinelConfig = field(default_factory=SentinelConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    lora: LoRaConfig = field(default_factory=LoRaConfig)
    power: PowerConfig = field(default_factory=PowerConfig)
    gps: GPSConfig = field(default_factory=GPSConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _build_dataclass(cls, data: dict):
    """Build a dataclass from a dict, ignoring unknown keys."""
    if data is None:
        return cls()
    valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_keys}
    return cls(**filtered)


def load_config(path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from a YAML file.

    Args:
        path: Path to config.yaml. Uses default if None.

    Returns:
        Fully populated AppConfig instance.
    """
    config_path = path or _DEFAULT_CONFIG_PATH

    if not os.path.exists(config_path):
        logger.warning(
            f"Config file not found at {config_path}. Using defaults."
        )
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    logger.info(f"Configuration loaded from {config_path}")

    return AppConfig(
        sentinel=_build_dataclass(SentinelConfig, raw.get("sentinel")),
        audio=_build_dataclass(AudioConfig, raw.get("audio")),
        inference=_build_dataclass(InferenceConfig, raw.get("inference")),
        lora=_build_dataclass(LoRaConfig, raw.get("lora")),
        power=_build_dataclass(PowerConfig, raw.get("power")),
        gps=_build_dataclass(GPSConfig, raw.get("gps")),
        logging=_build_dataclass(LoggingConfig, raw.get("logging")),
    )
