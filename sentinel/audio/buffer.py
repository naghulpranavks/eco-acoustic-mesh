"""
Circular Audio Buffer — Thread-Safe NumPy Ring Buffer

Manages a fixed-size, pre-allocated buffer for continuous audio capture.
Zero allocation after initialization. Single writer, single reader pattern.
"""

import numpy as np
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CircularAudioBuffer:
    """
    Thread-safe circular buffer backed by a pre-allocated NumPy array.

    Designed for single-producer (audio capture thread) and
    single-consumer (inference thread) with minimal lock contention.
    """

    def __init__(self, duration_sec: float, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.capacity = int(duration_sec * sample_rate)

        # Pre-allocate — zero allocation after this point
        self._buffer = np.zeros(self.capacity, dtype=np.float32)
        self._write_pos = 0
        self._samples_written = 0  # Monotonic counter
        self._lock = threading.Lock()

        logger.info(
            f"Audio buffer initialized: {duration_sec}s capacity, "
            f"{self.capacity} samples, "
            f"{self._buffer.nbytes / 1024:.1f} KB RAM"
        )

    @property
    def is_full(self) -> bool:
        """True if at least one full window has been captured."""
        return self._samples_written >= self.capacity

    @property
    def samples_available(self) -> int:
        """Number of valid samples in the buffer."""
        return min(self._samples_written, self.capacity)

    def write(self, data: np.ndarray) -> None:
        """
        Write audio samples into the buffer. Wraps automatically.

        Args:
            data: Float32 audio samples (mono). Any length accepted.
        """
        n = len(data)
        if n == 0:
            return

        with self._lock:
            if n >= self.capacity:
                # Data larger than buffer — keep only the tail
                self._buffer[:] = data[-self.capacity:]
                self._write_pos = 0
                self._samples_written += n
                return

            space_before_wrap = self.capacity - self._write_pos

            if n <= space_before_wrap:
                self._buffer[self._write_pos:self._write_pos + n] = data
            else:
                # Wrap around
                self._buffer[self._write_pos:] = data[:space_before_wrap]
                remainder = n - space_before_wrap
                self._buffer[:remainder] = data[space_before_wrap:]

            self._write_pos = (self._write_pos + n) % self.capacity
            self._samples_written += n

    def get_window(self, duration_sec: Optional[float] = None) -> Optional[np.ndarray]:
        """
        Extract the most recent audio window as a contiguous copy.

        Args:
            duration_sec: Window size in seconds. None = full buffer.

        Returns:
            Copy of audio as float32 array, or None if not enough data.
        """
        requested = int(
            (duration_sec or (self.capacity / self.sample_rate))
            * self.sample_rate
        )

        with self._lock:
            if self.samples_available < requested:
                return None

            read_start = (self._write_pos - requested) % self.capacity

            if read_start < self._write_pos:
                return self._buffer[read_start:self._write_pos].copy()
            else:
                part1 = self._buffer[read_start:]
                part2 = self._buffer[:self._write_pos]
                return np.concatenate([part1, part2])

    def clear(self) -> None:
        """Reset the buffer to empty state."""
        with self._lock:
            self._buffer.fill(0.0)
            self._write_pos = 0
            self._samples_written = 0
