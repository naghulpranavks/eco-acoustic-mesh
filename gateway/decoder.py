"""
LoRa Payload Decoder — Binary to JSON

Shared decoder used by the gateway server to convert
incoming 20-byte LoRa payloads into structured dicts.
"""

import time
from sentinel.comms.payload import (
    decode_payload,
    from_hex_string,
    MsgType,
)


def decode_to_dict(data: bytes) -> dict:
    """Decode a 20-byte binary LoRa payload into a JSON-friendly dict."""
    p = decode_payload(data)
    msg_types = {1: "alert", 2: "heartbeat", 3: "battery"}

    return {
        "msg_type": msg_types.get(p.msg_type, "unknown"),
        "threat": {
            "class": p.threat_name,
            "code": p.threat_class,
            "confidence": p.confidence,
        },
        "location": {
            "latitude": p.latitude,
            "longitude": p.longitude,
            "gps_valid": p.flags_decoded["gps_valid"],
        },
        "timestamp": p.timestamp,
        "timestamp_iso": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.timestamp)
        ),
        "node": {
            "id": p.node_id,
            "battery_pct": p.battery_pct,
            "cpu_temp_c": p.temp_c,
            "audio_db": p.audio_db,
        },
        "flags": p.flags_decoded,
    }


def decode_hex(hex_string: str) -> dict:
    """Decode a hex-encoded LoRa payload string into a dict."""
    return decode_to_dict(from_hex_string(hex_string))
