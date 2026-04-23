# Eco-Acoustic Mesh

**An ultra-edge, AI-powered anti-poaching sentinel network** using Google Gemma 4 E2B for real-time environmental sound classification on solar-powered edge devices.

> Built for the [Gemma 4 Good Hackathon](https://www.kaggle.com/competitions/gemma-4-good-hackathon) | Impact Area: **Global Resilience**

## What It Does

Solar-powered sentinel nodes deployed in protected wildlife areas continuously listen for threats:
- **Chainsaws** (illegal logging)
- **Gunshots** (poaching)
- **Vehicles** (unauthorized access)

When a threat is detected, a compact 20-byte alert is transmitted via LoRaWAN to a Ranger Dashboard, enabling rapid response.

## Architecture

```
[Mic] -> [Circular Buffer] -> [Silence Gate] -> [Gemma 4 E2B] -> [LoRa TX] -> [Dashboard]
         (5s rolling RAM)     (skip quiet)       (INT4 ~1.2GB)    (20 bytes)    (PWA/Phone)
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Simulation (No Hardware Required)
```bash
python scripts/simulate.py --cycles 20
```

### 3. Start Gateway + Dashboard
```bash
python -m gateway.server
# Open http://localhost:8000 on your phone
```

### 4. Run with Simulated Alerts
```bash
python scripts/simulate.py --gateway http://localhost:8000 --cycles 50
```

### 5. Run on Real Hardware (Raspberry Pi)
```bash
# Edit config.yaml: set simulation_mode: false
python -m sentinel.main
```

## Project Structure

```
sentinel/          # Edge node (Pi) — core Python package
  audio/           # Mic capture, circular buffer, preprocessor
  inference/       # Gemma E2B classifier + prompt engineering
  comms/           # LoRa payload encoder + UART transmitter
  power/           # Thermal monitoring + adaptive sleep
  main.py          # Orchestrator — the inference loop

gateway/           # LoRa -> Dashboard bridge (FastAPI)
dashboard/         # Ranger Dashboard (PWA, vanilla JS + Leaflet)
scripts/           # Simulation + setup scripts
tests/             # Test suite
notebooks/         # Colab notebooks for fine-tuning
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Edge AI Model | Gemma 4 E2B (INT4, ~1.2GB RAM) |
| Inference Runtime | Ollama |
| Audio Pipeline | sounddevice + NumPy circular buffer |
| Communications | LoRaWAN (20-byte binary payloads) |
| Gateway Server | FastAPI + SQLite |
| Ranger Dashboard | Vanilla JS + Leaflet.js (PWA) |
| Training | Google Colab notebooks |

## License

Apache 2.0
