"""Tests for the CircularAudioBuffer."""

import sys
import os
import numpy as np
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentinel.audio.buffer import CircularAudioBuffer


def test_basic_write_and_read():
    buf = CircularAudioBuffer(duration_sec=1.0, sample_rate=16000)
    assert buf.capacity == 16000

    # Write half a buffer
    data = np.ones(8000, dtype=np.float32) * 0.5
    buf.write(data)
    assert buf.samples_available == 8000
    assert not buf.is_full

    # Not enough for full window
    assert buf.get_window() is None

    # Write the rest
    buf.write(data)
    assert buf.is_full

    window = buf.get_window()
    assert window is not None
    assert len(window) == 16000


def test_wraparound():
    buf = CircularAudioBuffer(duration_sec=1.0, sample_rate=100)

    # Write 150 samples into a 100-sample buffer
    data1 = np.ones(70, dtype=np.float32) * 1.0
    data2 = np.ones(80, dtype=np.float32) * 2.0
    buf.write(data1)
    buf.write(data2)

    window = buf.get_window()
    assert window is not None
    assert len(window) == 100
    # Last 80 samples should be 2.0, first 20 should be 1.0
    assert np.all(window[-80:] == 2.0)


def test_partial_window():
    buf = CircularAudioBuffer(duration_sec=2.0, sample_rate=100)
    data = np.ones(200, dtype=np.float32)
    buf.write(data)

    # Request 1-second window from a 2-second buffer
    window = buf.get_window(duration_sec=1.0)
    assert window is not None
    assert len(window) == 100


def test_clear():
    buf = CircularAudioBuffer(duration_sec=1.0, sample_rate=100)
    buf.write(np.ones(100, dtype=np.float32))
    assert buf.is_full

    buf.clear()
    assert buf.samples_available == 0
    assert not buf.is_full


def test_thread_safety():
    """Verify no crashes under concurrent read/write."""
    buf = CircularAudioBuffer(duration_sec=1.0, sample_rate=16000)
    errors = []

    def writer():
        try:
            for _ in range(100):
                data = np.random.randn(800).astype(np.float32)
                buf.write(data)
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(100):
                buf.get_window(duration_sec=0.5)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0, f"Thread safety errors: {errors}"


if __name__ == "__main__":
    test_basic_write_and_read()
    test_wraparound()
    test_partial_window()
    test_clear()
    test_thread_safety()
    print("All buffer tests passed!")
