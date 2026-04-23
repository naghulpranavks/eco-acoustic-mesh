"""
Audio Capture Thread — Continuous Microphone Input

Streams audio from the system microphone into the circular buffer.
Uses sounddevice for cross-platform compatibility (Windows/Linux/macOS).
"""

import numpy as np
import threading
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AudioCapture:
    """
    Continuous audio capture from a microphone device.

    Runs in a dedicated daemon thread. Writes PCM samples directly
    into a CircularAudioBuffer with zero intermediate file I/O.
    """

    def __init__(
        self,
        buffer,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_sec: float = 0.5,
        device_index: Optional[int] = None,
    ):
        self.buffer = buffer
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = int(chunk_duration_sec * sample_rate)
        self.device_index = device_index

        self._stream = None
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error_count = 0
        self._max_retries = 5

    def _audio_callback(self, indata, frames, time_info, status):
        """
        Sounddevice callback — runs in the audio thread.
        Must be fast and non-blocking.
        """
        if status:
            logger.warning(f"Audio stream status: {status}")

        audio = indata[:, 0] if indata.ndim > 1 else indata.flatten()
        self.buffer.write(audio.astype(np.float32))

    def _capture_loop(self):
        """Main capture loop with automatic retry on failure."""
        import sounddevice as sd  # Import here to allow graceful fallback

        while self._running.is_set():
            try:
                logger.info(
                    f"Opening audio stream: {self.sample_rate}Hz, "
                    f"mono, device={self.device_index or 'default'}"
                )

                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    blocksize=self.chunk_size,
                    device=self.device_index,
                    callback=self._audio_callback,
                )

                self._stream.start()
                self._error_count = 0
                logger.info("Audio capture started successfully")

                # Block until stopped
                while self._running.is_set():
                    time.sleep(0.1)

            except Exception as e:
                self._error_count += 1
                backoff = min(2 ** self._error_count, 30)
                logger.error(
                    f"Audio capture error (attempt {self._error_count}/"
                    f"{self._max_retries}): {e}. Retrying in {backoff}s..."
                )

                if self._error_count >= self._max_retries:
                    logger.critical(
                        "Max audio retries exceeded. Capture thread exiting."
                    )
                    break

                time.sleep(backoff)

            finally:
                if self._stream is not None:
                    try:
                        self._stream.stop()
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None

    def start(self):
        """Start audio capture in a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Audio capture is already running")
            return

        self._running.set()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="AudioCapture",
            daemon=True,
        )
        self._thread.start()
        logger.info("Audio capture thread launched")

    def stop(self):
        """Stop the audio capture thread gracefully."""
        logger.info("Stopping audio capture...")
        self._running.clear()

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Audio capture thread did not stop cleanly")
            self._thread = None

        logger.info("Audio capture stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
