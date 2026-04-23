"""Tests for the LoRa payload encoder/decoder."""

import sys
import os
import struct
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentinel.comms.payload import (
    encode_alert, encode_heartbeat, decode_payload,
    to_hex_string, from_hex_string,
    ThreatCode, MsgType, PayloadFlags,
)


def test_encode_decode_roundtrip():
    """Encode an alert and decode it — all fields must match."""
    payload = encode_alert(
        threat_class=ThreatCode.CHAINSAW,
        confidence_pct=85,
        lat_udeg=-1948975,
        lon_udeg=34786740,
        node_id=7,
        audio_db=72,
        temp_c=53,
        battery_pct=88,
        flags=PayloadFlags.encode(gps_valid=True, solar_charging=True),
    )
    assert len(payload) == 20

    decoded = decode_payload(payload)
    assert decoded.msg_type == MsgType.ALERT
    assert decoded.threat_class == ThreatCode.CHAINSAW
    assert decoded.confidence == 85
    assert decoded.latitude_udeg == -1948975
    assert decoded.longitude_udeg == 34786740
    assert decoded.node_id == 7
    assert decoded.audio_db == 72
    assert decoded.temp_c == 53
    assert decoded.battery_pct == 88
    assert decoded.flags_decoded["gps_valid"] is True
    assert decoded.flags_decoded["solar_charging"] is True
    assert decoded.flags_decoded["buffer_overflow"] is False


def test_heartbeat():
    payload = encode_heartbeat(node_id=3, battery_pct=95, temp_c=42)
    assert len(payload) == 20
    decoded = decode_payload(payload)
    assert decoded.msg_type == MsgType.HEARTBEAT
    assert decoded.node_id == 3
    assert decoded.battery_pct == 95


def test_hex_roundtrip():
    payload = encode_alert(
        threat_class=ThreatCode.GUNSHOT,
        confidence_pct=92,
        lat_udeg=0,
        lon_udeg=0,
    )
    hex_str = to_hex_string(payload)
    restored = from_hex_string(hex_str)
    assert payload == restored


def test_payload_size():
    """Payload must always be exactly 20 bytes."""
    for code in [ThreatCode.CHAINSAW, ThreatCode.GUNSHOT, ThreatCode.VEHICLE]:
        p = encode_alert(threat_class=code, confidence_pct=50)
        assert len(p) == 20


def test_confidence_clamping():
    p = encode_alert(threat_class=ThreatCode.CHAINSAW, confidence_pct=150)
    decoded = decode_payload(p)
    assert decoded.confidence == 100

    p2 = encode_alert(threat_class=ThreatCode.CHAINSAW, confidence_pct=-10)
    decoded2 = decode_payload(p2)
    assert decoded2.confidence == 0


def test_threat_name():
    p = encode_alert(threat_class=ThreatCode.VEHICLE, confidence_pct=77)
    decoded = decode_payload(p)
    assert decoded.threat_name == "VEHICLE"


if __name__ == "__main__":
    test_encode_decode_roundtrip()
    test_heartbeat()
    test_hex_roundtrip()
    test_payload_size()
    test_confidence_clamping()
    test_threat_name()
    print("All payload tests passed!")
