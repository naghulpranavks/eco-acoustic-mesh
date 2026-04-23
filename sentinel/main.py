"""
Eco-Acoustic Mesh — Sentinel Main Loop

Entry point for the edge sentinel node. Orchestrates the full pipeline:
  Mic → Circular Buffer → Silence Gate → Gemma E2B → LoRa TX

Usage:
    python -m sentinel.main
    python -m sentinel.main --config path/to/config.yaml
"""

import sys
import time
import signal
import logging
import argparse

from sentinel.config import load_config
from sentinel.utils.logger import setup_logging
from sentinel.utils.gps import GPSReader
from sentinel.audio.buffer import CircularAudioBuffer
from sentinel.audio.capture import AudioCapture
from sentinel.audio.preprocessor import AudioPreprocessor
from sentinel.inference.classifier import GemmaClassifier, ThreatClass
from sentinel.comms.payload import (
    encode_alert,
    encode_heartbeat,
    ThreatCode,
    PayloadFlags,
)
from sentinel.comms.lora_transmitter import LoRaTransmitter
from sentinel.power.manager import PowerManager

logger = logging.getLogger(__name__)

# Map ThreatClass enum → payload ThreatCode
_CLASS_TO_CODE = {
    ThreatClass.CHAINSAW: ThreatCode.CHAINSAW,
    ThreatClass.GUNSHOT: ThreatCode.GUNSHOT,
    ThreatClass.VEHICLE: ThreatCode.VEHICLE,
    ThreatClass.AMBIENT: ThreatCode.AMBIENT,
    ThreatClass.UNKNOWN: ThreatCode.UNKNOWN,
}


class SentinelNode:
    """
    Main sentinel node controller.

    Manages the full lifecycle: audio capture → inference → LoRa TX.
    Handles graceful shutdown, error recovery, and power management.
    """

    def __init__(self, config_path=None):
        self.cfg = load_config(config_path)
        self._shutdown = False

        # --- Setup logging ---
        setup_logging(
            level=self.cfg.logging.level,
            log_file=self.cfg.logging.file,
            max_bytes=self.cfg.logging.max_bytes,
            backup_count=self.cfg.logging.backup_count,
        )

        logger.info("=" * 60)
        logger.info("  ECO-ACOUSTIC MESH — SENTINEL NODE")
        logger.info(f"  Node ID: {self.cfg.sentinel.node_id}")
        logger.info(f"  Simulation: {self.cfg.sentinel.simulation_mode}")
        logger.info("=" * 60)

        # --- Initialize components ---
        self.gps = GPSReader(
            use_gpsd=self.cfg.gps.use_gpsd,
            mock_latitude=self.cfg.gps.mock_latitude,
            mock_longitude=self.cfg.gps.mock_longitude,
        )

        self.audio_buffer = CircularAudioBuffer(
            duration_sec=self.cfg.audio.buffer_duration_sec,
            sample_rate=self.cfg.audio.sample_rate,
        )

        self.audio_capture = AudioCapture(
            buffer=self.audio_buffer,
            sample_rate=self.cfg.audio.sample_rate,
            channels=self.cfg.audio.channels,
            chunk_duration_sec=self.cfg.audio.chunk_duration_sec,
            device_index=self.cfg.audio.device_index,
        )

        self.preprocessor = AudioPreprocessor(
            sample_rate=self.cfg.audio.sample_rate,
            silence_threshold_db=self.cfg.audio.silence_threshold_db,
        )

        self.classifier = GemmaClassifier(
            model=self.cfg.inference.model,
            confidence_threshold=self.cfg.inference.confidence_threshold,
            max_inference_time_sec=self.cfg.inference.max_inference_time_sec,
            ollama_host=self.cfg.inference.ollama_host,
            use_minimal_prompt=self.cfg.inference.use_minimal_prompt,
        )

        self.lora = LoRaTransmitter(
            serial_port=self.cfg.lora.serial_port,
            baud_rate=self.cfg.lora.baud_rate,
            fport=self.cfg.lora.fport,
            retry_count=self.cfg.lora.retry_count,
            retry_delay_sec=self.cfg.lora.retry_delay_sec,
            simulation_mode=self.cfg.sentinel.simulation_mode,
        )

        self.power = PowerManager(
            thermal_limit_c=self.cfg.power.thermal_limit_c,
            base_sleep_sec=self.cfg.power.sleep_interval_sec,
            heartbeat_interval_sec=self.cfg.power.heartbeat_interval_sec,
            adaptive_sleep=self.cfg.power.adaptive_sleep,
        )

        # --- Register signal handlers ---
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name} — initiating graceful shutdown...")
        self._shutdown = True

    def _send_threat_alert(self, classification, audio_db: int):
        """Encode and transmit a threat alert via LoRa."""
        pos = self.gps.get_position()
        threat_code = _CLASS_TO_CODE.get(
            classification.threat_class, ThreatCode.UNKNOWN
        )

        payload = encode_alert(
            threat_class=threat_code,
            confidence_pct=int(classification.confidence * 100),
            lat_udeg=pos.lat_microdeg,
            lon_udeg=pos.lon_microdeg,
            node_id=self.cfg.sentinel.node_id,
            audio_db=audio_db,
            temp_c=int(self.power.get_cpu_temp()),
            battery_pct=self.power.get_battery_pct(),
            flags=PayloadFlags.encode(
                gps_valid=pos.valid,
                solar_charging=False,
            ),
        )

        success = self.lora.transmit(payload)
        if success:
            logger.info(
                f"🚨 Alert transmitted: {classification.threat_class.value} "
                f"@ ({pos.latitude:.4f}, {pos.longitude:.4f})"
            )
        else:
            logger.error("Failed to transmit threat alert!")

    def _send_heartbeat(self):
        """Send a periodic heartbeat status payload."""
        pos = self.gps.get_position()

        payload = encode_heartbeat(
            node_id=self.cfg.sentinel.node_id,
            battery_pct=self.power.get_battery_pct(),
            temp_c=int(self.power.get_cpu_temp()),
            lat_udeg=pos.lat_microdeg,
            lon_udeg=pos.lon_microdeg,
            flags=PayloadFlags.encode(gps_valid=pos.valid),
        )

        self.lora.transmit(payload)
        self.power.mark_heartbeat_sent()
        logger.info("💓 Heartbeat sent")

    def run(self):
        """
        Main inference loop.

        1. Wait for buffer to fill
        2. Extract audio window
        3. Silence gate — skip if quiet
        4. Gemma E2B classification
        5. If threat → encode + transmit LoRa payload
        6. Check thermals, send heartbeat if due
        7. Adaptive sleep
        """
        logger.info("Starting sentinel main loop...")
        self.audio_capture.start()

        # Wait for initial buffer fill
        logger.info(
            f"Waiting for audio buffer to fill "
            f"({self.cfg.audio.buffer_duration_sec}s)..."
        )
        while not self.audio_buffer.is_full and not self._shutdown:
            time.sleep(0.5)

        if self._shutdown:
            self._cleanup()
            return

        logger.info("Buffer full — entering inference loop")
        cycle = 0

        while not self._shutdown:
            cycle += 1

            try:
                # --- Step 1: Thermal check ---
                if self.power.is_overheating():
                    self.power.thermal_cooldown()

                # --- Step 2: Extract audio window ---
                audio = self.audio_buffer.get_window()
                if audio is None:
                    time.sleep(0.5)
                    continue

                # --- Step 3: Preprocess + silence gate ---
                analysis, wav_bytes = self.preprocessor.process(audio)

                if wav_bytes is None:
                    # Silent — skip inference to save power
                    self.power.report_ambient()

                    if cycle % 50 == 0:
                        logger.info(
                            f"Cycle {cycle}: Silent "
                            f"(RMS={analysis.rms_db:.1f}dB) — skipping"
                        )
                else:
                    # --- Step 4: Gemma E2B classification ---
                    result = self.classifier.classify(wav_bytes)

                    if (
                        result.is_threat
                        and result.confidence
                        >= self.cfg.inference.confidence_threshold
                    ):
                        # --- Step 5: Transmit alert ---
                        audio_db = int(max(0, analysis.peak_db + 100))
                        self._send_threat_alert(result, audio_db)
                        self.power.report_threat()
                    else:
                        self.power.report_ambient()

                # --- Step 6: Heartbeat ---
                if self.power.heartbeat_due():
                    self._send_heartbeat()

                # --- Step 7: Adaptive sleep ---
                sleep_time = self.power.get_sleep_interval()
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(
                    f"Error in inference loop cycle {cycle}: {e}",
                    exc_info=True,
                )
                time.sleep(5)  # Back off on error

        self._cleanup()

    def _cleanup(self):
        """Graceful shutdown of all components."""
        logger.info("Shutting down sentinel node...")
        self.audio_capture.stop()
        self.lora.close()

        stats = self.classifier.stats
        lora_stats = self.lora.stats
        logger.info(
            f"Session stats: "
            f"inferences={stats['total_inferences']}, "
            f"threats={stats['threats_detected']}, "
            f"LoRa TX={lora_stats['transmissions']}, "
            f"LoRa fails={lora_stats['failures']}"
        )
        logger.info("Sentinel node stopped. Goodbye. 🌿")


def main():
    parser = argparse.ArgumentParser(
        description="Eco-Acoustic Mesh — Sentinel Node"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.yaml (default: project root)",
    )
    args = parser.parse_args()

    node = SentinelNode(config_path=args.config)
    node.run()


if __name__ == "__main__":
    main()
