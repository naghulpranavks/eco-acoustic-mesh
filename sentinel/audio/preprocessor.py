"""
Audio Preprocessor — Silence Gating, Normalization, WAV Encoding

Processes raw audio buffers before inference.
All operations are in-memory with zero disk I/O.
"""

import numpy as np
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AudioAnalysis:
    """Results of audio preprocessing analysis."""
    rms_db: float
    peak_db: float
    is_silent: bool
    duration_sec: float
    sample_count: int


class AudioPreprocessor:
    """
    Preprocesses audio chunks for Gemma E2B inference.

    Pipeline: Silence Gate -> Normalize -> WAV Encode
    All operations are in-memory (no file I/O).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold_db: float = -40.0,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold_db = silence_threshold_db

    @staticmethod
    def compute_rms_db(audio: np.ndarray) -> float:
        """Compute RMS energy in decibels."""
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-10:
            return -100.0
        return 20.0 * np.log10(rms)

    @staticmethod
    def compute_peak_db(audio: np.ndarray) -> float:
        """Compute peak amplitude in decibels."""
        peak = np.max(np.abs(audio))
        if peak < 1e-10:
            return -100.0
        return 20.0 * np.log10(peak)

    def analyze(self, audio: np.ndarray) -> AudioAnalysis:
        """Analyze an audio chunk without modifying it."""
        rms_db = self.compute_rms_db(audio)
        peak_db = self.compute_peak_db(audio)
        return AudioAnalysis(
            rms_db=rms_db,
            peak_db=peak_db,
            is_silent=rms_db < self.silence_threshold_db,
            duration_sec=len(audio) / self.sample_rate,
            sample_count=len(audio),
        )

    @staticmethod
    def normalize(audio: np.ndarray) -> np.ndarray:
        """Peak-normalize audio to [-1.0, 1.0] range."""
        peak = np.max(np.abs(audio))
        if peak < 1e-10:
            return audio.copy()
        return audio / peak

    def to_wav_bytes(self, audio: np.ndarray, do_normalize: bool = True) -> bytes:
        """
        Encode audio to WAV format in memory (no disk I/O).

        Args:
            audio: Float32 audio array (mono).
            do_normalize: Whether to peak-normalize before encoding.

        Returns:
            WAV file content as bytes.
        """
        import soundfile as sf

        if do_normalize:
            audio = self.normalize(audio)

        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, audio, self.sample_rate, format="WAV", subtype="FLOAT")
        wav_buffer.seek(0)
        return wav_buffer.read()

    def process(self, audio: np.ndarray):
        """
        Full preprocessing pipeline: analyze -> gate -> normalize -> encode.

        Args:
            audio: Raw float32 audio from the circular buffer.

        Returns:
            Tuple of (AudioAnalysis, wav_bytes or None).
            wav_bytes is None if audio is silent.
        """
        analysis = self.analyze(audio)

        if analysis.is_silent:
            logger.debug(
                f"Silence: RMS={analysis.rms_db:.1f}dB "
                f"(threshold={self.silence_threshold_db}dB)"
            )
            return analysis, None

        wav_bytes = self.to_wav_bytes(audio, do_normalize=True)

        logger.debug(
            f"Audio processed: {analysis.duration_sec:.1f}s, "
            f"RMS={analysis.rms_db:.1f}dB, WAV={len(wav_bytes)} bytes"
        )
        return analysis, wav_bytes
