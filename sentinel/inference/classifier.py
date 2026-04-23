"""
Gemma E2B Threat Classifier — Ollama Integration

Wraps the Ollama Python client to send audio chunks to Gemma 4 E2B
for environmental sound classification. Handles timeout, JSON parsing,
and graceful degradation.
"""

import json
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from sentinel.inference.prompts import (
    SYSTEM_PROMPT,
    CLASSIFY_PROMPT,
    CLASSIFY_PROMPT_MINIMAL,
)

logger = logging.getLogger(__name__)


class ThreatClass(Enum):
    """Classification categories for detected sounds."""
    CHAINSAW = "CHAINSAW"
    GUNSHOT = "GUNSHOT"
    VEHICLE = "VEHICLE"
    AMBIENT = "AMBIENT"
    UNKNOWN = "UNKNOWN"


@dataclass
class ThreatClassification:
    """Result of a single classification inference."""
    threat_class: ThreatClass
    confidence: float
    reasoning: str = ""
    inference_time_sec: float = 0.0
    raw_response: str = ""
    is_threat: bool = field(init=False)

    def __post_init__(self):
        self.is_threat = self.threat_class not in (
            ThreatClass.AMBIENT, ThreatClass.UNKNOWN
        )


class GemmaClassifier:
    """
    Audio threat classifier using Gemma 4 E2B via Ollama.

    Sends audio WAV bytes to the model with environmental sound
    classification prompts and parses the structured JSON response.
    """

    def __init__(
        self,
        model: str = "gemma4:e2b",
        confidence_threshold: float = 0.70,
        max_inference_time_sec: float = 15.0,
        ollama_host: str = "http://localhost:11434",
        use_minimal_prompt: bool = False,
    ):
        self.model = model
        self.confidence_threshold = confidence_threshold
        self.max_inference_time_sec = max_inference_time_sec
        self.ollama_host = ollama_host
        self.use_minimal_prompt = use_minimal_prompt
        self._client = None
        self._inference_count = 0
        self._threat_count = 0

    def _get_client(self):
        """Lazy-initialize the Ollama client."""
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self.ollama_host)
                logger.info(f"Ollama client connected: {self.ollama_host}")
            except ImportError:
                logger.error("ollama package not installed. pip install ollama")
                raise
        return self._client

    def _parse_response(self, raw: str):
        """Parse the JSON classification response from Gemma."""
        text = raw.strip()

        # Strip markdown code fences
        if "```" in text:
            lines = text.split("\n")
            text = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end == 0:
            logger.warning(f"No JSON in response: {text[:200]}")
            return ThreatClass.UNKNOWN, 0.0, "Parse failure: no JSON"

        try:
            data = json.loads(text[start:end])
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}. Raw: {text[:200]}")
            return ThreatClass.UNKNOWN, 0.0, f"JSON error: {e}"

        raw_class = data.get("class", "UNKNOWN").upper().strip()
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        reasoning = data.get("reasoning", "")

        try:
            threat_class = ThreatClass(raw_class)
        except ValueError:
            logger.warning(f"Unknown threat class: {raw_class}")
            threat_class = ThreatClass.UNKNOWN

        return threat_class, confidence, reasoning

    def classify(self, wav_bytes: bytes) -> ThreatClassification:
        """
        Classify an audio segment using Gemma 4 E2B.

        Args:
            wav_bytes: WAV-encoded audio bytes (16kHz, mono, float32).

        Returns:
            ThreatClassification with class, confidence, and metadata.
        """
        prompt = (
            CLASSIFY_PROMPT_MINIMAL if self.use_minimal_prompt
            else CLASSIFY_PROMPT
        )

        start_time = time.time()
        result = [None]
        error = [None]

        def _run_inference():
            try:
                client = self._get_client()
                response = client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [wav_bytes],  # Audio via multimodal input
                        },
                    ],
                )
                result[0] = response["message"]["content"]
            except Exception as e:
                error[0] = e

        # Run inference with timeout
        thread = threading.Thread(target=_run_inference, daemon=True)
        thread.start()
        thread.join(timeout=self.max_inference_time_sec)

        elapsed = time.time() - start_time

        if thread.is_alive():
            logger.warning(
                f"Inference timeout after {self.max_inference_time_sec}s"
            )
            return ThreatClassification(
                threat_class=ThreatClass.UNKNOWN,
                confidence=0.0,
                reasoning="Inference timed out",
                inference_time_sec=elapsed,
            )

        if error[0] is not None:
            logger.error(f"Inference error: {error[0]}")
            return ThreatClassification(
                threat_class=ThreatClass.UNKNOWN,
                confidence=0.0,
                reasoning=f"Error: {error[0]}",
                inference_time_sec=elapsed,
            )

        # Parse the response
        threat_class, confidence, reasoning = self._parse_response(result[0])
        self._inference_count += 1

        classification = ThreatClassification(
            threat_class=threat_class,
            confidence=confidence,
            reasoning=reasoning,
            inference_time_sec=elapsed,
            raw_response=result[0] or "",
        )

        if classification.is_threat and confidence >= self.confidence_threshold:
            self._threat_count += 1
            logger.warning(
                f"🚨 THREAT DETECTED: {threat_class.value} "
                f"(confidence={confidence:.2f}, time={elapsed:.1f}s)"
            )
        else:
            logger.info(
                f"Classification: {threat_class.value} "
                f"(confidence={confidence:.2f}, time={elapsed:.1f}s)"
            )

        return classification

    @property
    def stats(self) -> dict:
        """Inference statistics."""
        return {
            "total_inferences": self._inference_count,
            "threats_detected": self._threat_count,
        }
