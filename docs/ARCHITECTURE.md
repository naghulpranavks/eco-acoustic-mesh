# Eco-Acoustic Mesh — Technical Architecture

## System Overview

Eco-Acoustic Mesh is an edge-deployed AI sentinel network for wildlife protection. Solar-powered sensor nodes continuously monitor protected areas for illegal activity (logging, poaching, unauthorized vehicle access) using Google Gemma 4 E2B's native audio encoder for environmental sound classification.

### Design Principles

1. **Local-First:** All inference runs on-device. No cloud dependency for threat detection.
2. **Zero File I/O:** Audio is processed entirely in RAM via circular buffers — no disk writes.
3. **Power-Efficient:** Adaptive sleep scheduling and silence gating minimize CPU usage.
4. **Ultra-Low Bandwidth:** 20-byte binary payloads over LoRaWAN — works in areas with zero cellular coverage.
5. **Graceful Degradation:** Every component has fallback behavior — serial failures, inference timeouts, GPS loss.

---

## Architecture Diagram

```
                    PROTECTED WILDLIFE AREA
    ┌──────────────────────────────────────────────┐
    │                                              │
    │  ┌─────────────┐    ┌─────────────┐          │
    │  │ Sentinel #1  │    │ Sentinel #2  │   ...   │
    │  │ (Pi + Solar) │    │ (Pi + Solar) │         │
    │  └──────┬───────┘    └──────┬───────┘         │
    │         │ LoRa 868MHz       │ LoRa            │
    │         └────────┬──────────┘                 │
    │                  │                            │
    │           ┌──────┴──────┐                     │
    │           │ LoRa Gateway│                     │
    │           └──────┬──────┘                     │
    └──────────────────┼───────────────────────────┘
                       │ IP / WiFi / Satellite
                ┌──────┴──────┐
                │   Gateway   │
                │   Server    │
                │ (FastAPI)   │
                └──────┬──────┘
                       │ HTTP / SSE
                ┌──────┴──────┐
                │   Ranger    │
                │  Dashboard  │
                │   (PWA)     │
                └─────────────┘
```

---

## Sentinel Node — Edge Pipeline

### Data Flow

```
 Microphone (16kHz mono)
      │
      ▼
 ┌────────────────────────┐
 │  Audio Capture Thread   │  sounddevice callback
 │  (daemon, non-blocking) │  writes to buffer
 └───────────┬─────────────┘
             │ float32 PCM samples
             ▼
 ┌────────────────────────┐
 │  Circular Audio Buffer  │  NumPy ring buffer
 │  5s window, 312.5 KB   │  pre-allocated, zero-alloc
 │  thread-safe (1W/1R)    │  after init
 └───────────┬─────────────┘
             │ get_window() → contiguous copy
             ▼
 ┌────────────────────────┐
 │  Audio Preprocessor     │
 │  ┌─ RMS Energy Check ──┐│  < -40dB? → skip
 │  │  (silence gate)     ││  saves ~70% of cycles
 │  └─────────────────────┘│
 │  ┌─ Peak Normalize ────┐│  [-1.0, 1.0]
 │  └─────────────────────┘│
 │  ┌─ WAV Encode ────────┐│  in-memory via BytesIO
 │  │  (no disk I/O)      ││  ~640KB WAV for 5s
 │  └─────────────────────┘│
 └───────────┬─────────────┘
             │ WAV bytes (or None if silent)
             ▼
 ┌────────────────────────┐
 │  Gemma 4 E2B Classifier │  via Ollama API
 │                         │
 │  Prompt Engineering:    │
 │  • Role: Sound Analyst  │
 │  • Chain-of-thought     │
 │  • Structured JSON out  │
 │                         │
 │  Timeout: 15s max       │
 │  Output: {class, conf}  │
 └───────────┬─────────────┘
             │ ThreatClassification
             ▼
 ┌────────────────────────┐
 │  Decision Gate          │
 │  confidence >= 0.70?    │
 │  class != AMBIENT?      │
 └───┬──────────────┬──────┘
     │ NO           │ YES
     ▼              ▼
  [sleep]     ┌────────────────┐
              │ Payload Encoder │  struct.pack
              │ 20 bytes binary │  little-endian
              └───────┬────────┘
                      │ hex string
                      ▼
              ┌────────────────┐
              │ LoRa TX (UART) │  AT+SEND
              │ 3x retry logic │  serial @ 9600
              └────────────────┘
```

### Memory Budget (Raspberry Pi 4, 4GB)

| Component | RAM Usage |
|-----------|----------|
| OS + System | ~800 MB |
| Ollama daemon | ~200 MB |
| Gemma E2B INT4 weights | ~1,200 MB |
| Audio buffer (5s × 16kHz × f32) | 0.3 MB |
| WAV encoding buffer | 0.6 MB |
| Python interpreter + modules | ~100 MB |
| **Total** | **~2.3 GB** |
| **Headroom** | **~1.7 GB** |

### Power Budget (Solar Panel + Battery)

| State | Power Draw | Duration |
|-------|-----------|----------|
| Idle (silence, sleeping) | ~2.5W | ~70% of time |
| Active inference | ~7W | ~2s per cycle |
| LoRa transmission | ~0.5W | ~0.5s |
| **Average** | **~3.5W** | |

With a 20W solar panel + 10Ah battery → **continuous 24/7 operation**.

---

## LoRa Payload Protocol

### Binary Format (20 bytes, little-endian)

```
Offset  Size  Type    Field
──────  ────  ──────  ─────────────────
0       1     uint8   msg_type (0x01=alert, 0x02=heartbeat)
1       1     uint8   threat_class (0x01=chainsaw, 0x02=gunshot, 0x03=vehicle)
2       1     uint8   confidence (0-100%)
3-6     4     int32   latitude (microdegrees)
7-10    4     int32   longitude (microdegrees)
11-14   4     uint32  timestamp (unix epoch)
15      1     uint8   battery_pct (0-100%)
16      1     uint8   node_id (0-255)
17      1     uint8   audio_db (peak amplitude)
18      1     uint8   cpu_temp_c
19      1     uint8   flags (bitfield)

Flags: bit0=GPS_valid, bit1=solar_charging, bit2=buffer_overflow
```

### Why 20 bytes?

LoRaWAN payload limits by Spreading Factor:

| SF | Max Payload | Our Payload | Margin |
|----|------------|-------------|--------|
| SF7 | 222 bytes | 20 bytes | 91% unused |
| SF10 | 51 bytes | 20 bytes | 61% unused |
| SF12 | 51 bytes | 20 bytes | 61% unused |

Our 20-byte payload works at **any spreading factor**, maximizing range.

---

## Gemma E2B — Audio Classification Strategy

### Challenge
Gemma 4 E2B's audio encoder is optimized for **speech recognition**, not environmental sound classification. The model has never been explicitly trained to distinguish chainsaws from gunshots.

### Solution: Prompt-Engineered Audio Classification

1. **Role Prompting:** Prime the model as an "Environmental Sound Analyst" to override speech transcription defaults.
2. **Chain-of-Thought:** Ask the model to describe acoustic characteristics before classifying, improving reasoning accuracy.
3. **Structured Output:** Constrain output to strict JSON format for reliable downstream parsing.
4. **Fine-Tuning (Optional):** LoRA fine-tuning on ESC-50 dataset (see `notebooks/gemma4_e2b_finetune.ipynb`) to adapt the audio encoder's embedding space for non-speech sounds.

### Classification Prompt

```
SYSTEM: You are an Environmental Sound Analyst deployed in a wildlife
protection zone. Classify audio into: CHAINSAW, GUNSHOT, VEHICLE, or AMBIENT.

USER: Analyze the provided audio segment.
Think step by step:
1. What acoustic characteristics do you observe?
2. Does this match any threat category?
3. How confident are you?

Respond with ONLY valid JSON:
{"class": "<CATEGORY>", "confidence": <0.0-1.0>, "reasoning": "<brief>"}
```

---

## Gateway Server

- **Framework:** FastAPI (async, lightweight)
- **Database:** SQLite (no external DB dependencies)
- **Real-time:** Server-Sent Events (SSE) for live dashboard updates
- **Endpoints:**
  - `POST /api/webhook` — Receive LoRa payloads from TTN/ChirpStack
  - `POST /api/simulate` — Inject test alerts
  - `GET /api/alerts` — Fetch recent alerts (paginated)
  - `GET /api/nodes` — Node status summaries
  - `GET /api/alerts/stream` — SSE real-time feed
  - `GET /api/health` — Health check

---

## Ranger Dashboard (PWA)

- **Stack:** Vanilla HTML/CSS/JS — zero build step, zero dependencies beyond Leaflet
- **Map:** Leaflet.js with CartoDB dark tiles
- **Real-time:** SSE with polling fallback
- **Offline:** PWA manifest for "Add to Home Screen" on ranger's phone
- **Design:** Dark theme optimized for night-time operations

---

## Deployment Modes

### Simulation Mode (Demo / Development)
```bash
# Terminal 1: Start gateway
python -m gateway.server

# Terminal 2: Send simulated alerts
python scripts/simulate.py --gateway http://localhost:8000 --cycles 50
```

### Production Mode (Raspberry Pi)
```bash
# On the Pi:
ollama pull gemma4:e2b          # Or: ollama create eco-mesh -f Modelfile
python -m sentinel.main          # Starts inference loop

# At base station:
python -m gateway.server         # Starts dashboard
```

---

## Testing Strategy

| Test | File | Coverage |
|------|------|----------|
| Buffer integrity | `tests/test_buffer.py` | Write/read, wrap, thread safety |
| Payload encoding | `tests/test_payload.py` | Roundtrip, hex, clamping |
| End-to-end simulation | `scripts/simulate.py` | Full pipeline without hardware |
