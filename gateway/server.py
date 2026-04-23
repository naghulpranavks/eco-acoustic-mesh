"""
Gateway Server — FastAPI Bridge from LoRa Network to Ranger Dashboard

Receives decoded LoRa payloads (via webhook or simulation POST),
stores them in SQLite, and serves them to the dashboard via REST + SSE.
Also serves the built dashboard as static files.
"""

import os
import json
import time
import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from gateway.decoder import decode_hex, decode_to_dict

logger = logging.getLogger(__name__)

# --- Database Setup ---
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "alerts.db"
)

# In-memory alert queue for SSE streaming
_alert_queue: asyncio.Queue = asyncio.Queue()


def _init_db():
    """Create the alerts table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_type TEXT NOT NULL,
            threat_class TEXT,
            confidence INTEGER DEFAULT 0,
            latitude REAL,
            longitude REAL,
            gps_valid INTEGER DEFAULT 0,
            timestamp INTEGER,
            timestamp_iso TEXT,
            node_id INTEGER,
            battery_pct INTEGER,
            cpu_temp_c INTEGER,
            audio_db INTEGER,
            raw_json TEXT,
            received_at REAL DEFAULT (strftime('%s','now'))
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized: {DB_PATH}")


def _insert_alert(alert_dict: dict):
    """Insert a decoded alert into SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO alerts
        (msg_type, threat_class, confidence, latitude, longitude,
         gps_valid, timestamp, timestamp_iso, node_id, battery_pct,
         cpu_temp_c, audio_db, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            alert_dict["msg_type"],
            alert_dict["threat"]["class"],
            alert_dict["threat"]["confidence"],
            alert_dict["location"]["latitude"],
            alert_dict["location"]["longitude"],
            1 if alert_dict["location"]["gps_valid"] else 0,
            alert_dict["timestamp"],
            alert_dict["timestamp_iso"],
            alert_dict["node"]["id"],
            alert_dict["node"]["battery_pct"],
            alert_dict["node"]["cpu_temp_c"],
            alert_dict["node"]["audio_db"],
            json.dumps(alert_dict),
        ),
    )
    conn.commit()
    conn.close()


def _get_alerts(limit: int = 100, threat_only: bool = False) -> list:
    """Fetch recent alerts from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM alerts"
    if threat_only:
        query += " WHERE threat_class NOT IN ('AMBIENT', 'UNKNOWN')"
    query += " ORDER BY id DESC LIMIT ?"

    rows = conn.execute(query, (limit,)).fetchall()
    conn.close()

    return [
        json.loads(row["raw_json"]) for row in rows
    ]


def _get_nodes() -> list:
    """Get latest status for each node."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT node_id, battery_pct, cpu_temp_c, timestamp_iso,
               MAX(id) as latest
        FROM alerts
        GROUP BY node_id
        ORDER BY node_id
    """).fetchall()
    conn.close()

    return [
        {
            "node_id": row["node_id"],
            "battery_pct": row["battery_pct"],
            "cpu_temp_c": row["cpu_temp_c"],
            "last_seen": row["timestamp_iso"],
        }
        for row in rows
    ]


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    logger.info("Gateway server started")
    yield
    logger.info("Gateway server stopped")


app = FastAPI(
    title="Eco-Acoustic Mesh Gateway",
    description="LoRa → Dashboard bridge for anti-poaching sentinel network",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Endpoints ---

@app.post("/api/webhook")
async def receive_webhook(request: Request):
    """Receive a decoded LoRa payload from TTN/ChirpStack webhook."""
    body = await request.json()

    # Handle TTN format or raw hex
    if "payload_hex" in body:
        alert = decode_hex(body["payload_hex"])
    elif "payload_raw" in body:
        raw_bytes = bytes.fromhex(body["payload_raw"])
        alert = decode_to_dict(raw_bytes)
    else:
        # Assume it's already a decoded alert dict
        alert = body

    _insert_alert(alert)
    await _alert_queue.put(alert)

    logger.info(
        f"Webhook received: {alert['msg_type']} — "
        f"{alert['threat']['class']}"
    )
    return {"status": "ok", "alert": alert}


@app.post("/api/simulate")
async def simulate_alert(request: Request):
    """Inject a simulated alert (for demo/testing)."""
    body = await request.json()
    _insert_alert(body)
    await _alert_queue.put(body)
    return {"status": "ok", "simulated": True}


@app.get("/api/alerts")
async def get_alerts(
    limit: int = 100,
    threats_only: bool = False,
):
    """Get recent alerts."""
    alerts = _get_alerts(limit=limit, threat_only=threats_only)
    return {"alerts": alerts, "count": len(alerts)}


@app.get("/api/nodes")
async def get_nodes():
    """Get status of all sentinel nodes."""
    nodes = _get_nodes()
    return {"nodes": nodes}


@app.get("/api/alerts/stream")
async def stream_alerts():
    """SSE endpoint for real-time alert streaming."""
    async def event_generator():
        while True:
            try:
                alert = await asyncio.wait_for(
                    _alert_queue.get(), timeout=30.0
                )
                yield f"data: {json.dumps(alert)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive
                yield f": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "healthy", "timestamp": time.time()}


# --- Static file serving for dashboard ---
# Serve from source dir (no build step needed — vanilla HTML/CSS/JS)
_dashboard_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "dashboard",
)
# Also check dist/ for production builds
_dashboard_dist = os.path.join(_dashboard_dir, "dist")

_serve_dir = _dashboard_dist if os.path.isdir(_dashboard_dist) else _dashboard_dir
if os.path.isdir(_serve_dir):
    app.mount(
        "/",
        StaticFiles(directory=_serve_dir, html=True),
        name="dashboard",
    )


def start_server(host="0.0.0.0", port=8000):
    """Start the gateway server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
