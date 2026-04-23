"""
Full Simulation Script — Demo Without Hardware

Simulates the entire Eco-Acoustic Mesh pipeline:
  - Generates synthetic audio (sine waves for threats, noise for ambient)
  - Runs through the preprocessing pipeline
  - Sends classification results to the gateway server
  - No microphone, LoRa hardware, or Ollama required

Usage:
    python scripts/simulate.py
    python scripts/simulate.py --gateway http://localhost:8000
"""

import sys
import os
import time
import json
import random
import logging
import argparse
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentinel.audio.buffer import CircularAudioBuffer
from sentinel.audio.preprocessor import AudioPreprocessor
from sentinel.comms.payload import (
    encode_alert, encode_heartbeat, decode_payload,
    ThreatCode, PayloadFlags, to_hex_string,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("simulator")

SAMPLE_RATE = 16000
DURATION = 5.0  # seconds


def generate_chainsaw_audio(duration=DURATION, sr=SAMPLE_RATE):
    """Generate synthetic chainsaw-like audio (buzzing + harmonics)."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    # Base frequency with harmonics
    signal = (
        0.3 * np.sin(2 * np.pi * 200 * t)
        + 0.2 * np.sin(2 * np.pi * 400 * t)
        + 0.15 * np.sin(2 * np.pi * 800 * t)
        + 0.1 * np.sin(2 * np.pi * 1600 * t)
    )
    # Add amplitude modulation (load variation)
    modulation = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    signal *= modulation
    # Add noise
    signal += 0.05 * np.random.randn(len(t)).astype(np.float32)
    return signal


def generate_gunshot_audio(duration=DURATION, sr=SAMPLE_RATE):
    """Generate synthetic gunshot-like audio (impulse + decay)."""
    n = int(sr * duration)
    signal = np.zeros(n, dtype=np.float32)
    # Place 1-3 gunshot impulses
    num_shots = random.randint(1, 3)
    for i in range(num_shots):
        pos = int(n * (0.1 + 0.25 * i))
        if pos < n:
            # Sharp impulse
            impulse_len = int(sr * 0.02)
            end = min(pos + impulse_len, n)
            t_imp = np.arange(end - pos, dtype=np.float32)
            signal[pos:end] = 0.9 * np.exp(-t_imp / (sr * 0.003)) * np.sin(
                2 * np.pi * 2000 * t_imp / sr
            )
    # Add light ambient noise
    signal += 0.02 * np.random.randn(n).astype(np.float32)
    return signal


def generate_vehicle_audio(duration=DURATION, sr=SAMPLE_RATE):
    """Generate synthetic engine/vehicle audio (low-freq rumble)."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    signal = (
        0.3 * np.sin(2 * np.pi * 80 * t)
        + 0.2 * np.sin(2 * np.pi * 160 * t)
        + 0.1 * np.sin(2 * np.pi * 240 * t)
    )
    signal += 0.08 * np.random.randn(len(t)).astype(np.float32)
    return signal


def generate_ambient_audio(duration=DURATION, sr=SAMPLE_RATE):
    """Generate quiet ambient noise (wind/nature)."""
    n = int(sr * duration)
    signal = 0.005 * np.random.randn(n).astype(np.float32)
    return signal


GENERATORS = {
    "CHAINSAW": (generate_chainsaw_audio, ThreatCode.CHAINSAW),
    "GUNSHOT": (generate_gunshot_audio, ThreatCode.GUNSHOT),
    "VEHICLE": (generate_vehicle_audio, ThreatCode.VEHICLE),
    "AMBIENT": (generate_ambient_audio, ThreatCode.AMBIENT),
}


def run_simulation(gateway_url=None, cycles=20):
    """Run a full simulation cycle."""
    buffer = CircularAudioBuffer(duration_sec=DURATION, sample_rate=SAMPLE_RATE)
    preprocessor = AudioPreprocessor(
        sample_rate=SAMPLE_RATE, silence_threshold_db=-40.0
    )

    logger.info("=" * 50)
    logger.info("  ECO-ACOUSTIC MESH — SIMULATION MODE")
    logger.info("=" * 50)

    threats = ["CHAINSAW", "GUNSHOT", "VEHICLE"]
    scenarios = (
        ["AMBIENT"] * 5
        + threats
        + ["AMBIENT"] * 3
        + threats
        + ["AMBIENT"] * 4
    )
    random.shuffle(scenarios)
    scenarios = scenarios[:cycles]

    for i, scenario in enumerate(scenarios, 1):
        gen_func, threat_code = GENERATORS[scenario]
        audio = gen_func()

        # Write to buffer
        buffer.clear()
        buffer.write(audio)

        # Preprocess
        window = buffer.get_window()
        analysis, wav_bytes = preprocessor.process(window)

        is_threat = scenario != "AMBIENT"
        confidence = random.uniform(0.75, 0.98) if is_threat else random.uniform(0.1, 0.4)

        logger.info(
            f"[{i}/{cycles}] Scenario: {scenario:10s} | "
            f"RMS: {analysis.rms_db:6.1f}dB | "
            f"Silent: {analysis.is_silent} | "
            f"Confidence: {confidence:.2f}"
        )

        if is_threat and wav_bytes is not None:
            payload = encode_alert(
                threat_class=threat_code,
                confidence_pct=int(confidence * 100),
                lat_udeg=-1948975,
                lon_udeg=34786740,
                node_id=1,
                audio_db=int(max(0, analysis.peak_db + 100)),
                temp_c=random.randint(40, 55),
                battery_pct=random.randint(60, 100),
                flags=PayloadFlags.encode(gps_valid=True),
            )
            decoded = decode_payload(payload)
            logger.info(
                f"  📡 LoRa Payload: {to_hex_string(payload)} "
                f"({len(payload)} bytes)"
            )
            logger.info(
                f"  🚨 ALERT: {decoded.threat_name} @ "
                f"({decoded.latitude:.4f}, {decoded.longitude:.4f})"
            )

            # POST to gateway if URL provided
            if gateway_url:
                _post_to_gateway(gateway_url, payload, confidence, scenario)

        time.sleep(0.5)

    logger.info("=" * 50)
    logger.info("  SIMULATION COMPLETE")
    logger.info("=" * 50)


def _post_to_gateway(url, payload_bytes, confidence, threat_class):
    """POST a simulated alert to the gateway server."""
    try:
        import httpx
        alert = {
            "msg_type": "alert",
            "threat": {
                "class": threat_class,
                "code": 0,
                "confidence": int(confidence * 100),
            },
            "location": {
                "latitude": -1.948975,
                "longitude": 34.786740,
                "gps_valid": True,
            },
            "timestamp": int(time.time()),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "node": {
                "id": 1,
                "battery_pct": random.randint(60, 100),
                "cpu_temp_c": random.randint(40, 55),
                "audio_db": random.randint(50, 90),
            },
            "flags": {"gps_valid": True, "solar_charging": False, "buffer_overflow": False},
        }
        resp = httpx.post(f"{url}/api/simulate", json=alert, timeout=5)
        logger.info(f"  → Gateway response: {resp.status_code}")
    except Exception as e:
        logger.warning(f"  → Gateway POST failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eco-Mesh Simulator")
    parser.add_argument(
        "--gateway", type=str, default=None,
        help="Gateway server URL (e.g. http://localhost:8000)",
    )
    parser.add_argument(
        "--cycles", type=int, default=20,
        help="Number of simulation cycles",
    )
    args = parser.parse_args()
    run_simulation(gateway_url=args.gateway, cycles=args.cycles)
