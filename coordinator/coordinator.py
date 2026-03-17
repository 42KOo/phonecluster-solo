#!/usr/bin/env python3
"""
PhoneCluster Coordinator - Solo edition

Endpoints:
  POST /register       - node registration
  POST /heartbeat      - keepalive
  GET  /status         - full cluster status (JSON)
  GET  /nodes          - node list
  GET  /health         - coordinator health check
  GET  /metrics/json   - quick metrics snapshot (cpu, mem, disk)
"""

import logging
import os
import socket
import sqlite3
import threading
import time
from functools import wraps

from flask import Flask, abort, jsonify, request


###############################################################################
# Config
###############################################################################

DB_PATH = os.environ.get("PC_DB_PATH", "/data/phonecluster/coordinator.db")
API_KEY = os.environ.get("PC_API_KEY", "changeme")
PORT = int(os.environ.get("PC_COORDINATOR_PORT", 7777))
HEARTBEAT_TTL = int(os.environ.get("PC_HEARTBEAT_TTL", 90))
SWEEP_INTERVAL = 30
CONFIG_FILE = "/etc/phonecluster/config.env"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [coordinator] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

###############################################################################
# DB
###############################################################################

_db_lock = threading.Lock()


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_lock, get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id       TEXT PRIMARY KEY,
                role          TEXT NOT NULL,
                ip            TEXT NOT NULL,
                port          INTEGER NOT NULL,
                registered_at REAL NOT NULL,
                last_seen     REAL NOT NULL,
                online        INTEGER NOT NULL DEFAULT 1,
                meta          TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL NOT NULL,
                node_id    TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail     TEXT
            )
        """)
        db.commit()
    log.info("DB ready: %s", DB_PATH)


###############################################################################
# Auth
###############################################################################


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != API_KEY:
            abort(401, "Invalid or missing API key")
        return f(*args, **kwargs)

    return decorated


###############################################################################
# Sweeper thread
###############################################################################


def sweeper():
    while True:
        time.sleep(SWEEP_INTERVAL)
        cutoff = time.time() - HEARTBEAT_TTL
        with _db_lock, get_db() as db:
            gone = db.execute(
                "SELECT node_id FROM nodes WHERE online=1 AND last_seen < ?",
                (cutoff,),
            ).fetchall()
            for row in gone:
                db.execute(
                    "UPDATE nodes SET online=0 WHERE node_id=?",
                    (row["node_id"],),
                )
                db.execute(
                    "INSERT INTO events(ts,node_id,event_type,detail) VALUES(?,?,?,?)",
                    (time.time(), row["node_id"], "offline", "heartbeat TTL exceeded"),
                )
                log.warning("Node offline: %s", row["node_id"])
            if gone:
                db.commit()


###############################################################################
# Self-registration
###############################################################################


def self_register():
    cfg = {}
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except FileNotFoundError:
        pass

    node_id = cfg.get("NODE_ID", socket.gethostname())
    role = cfg.get("NODE_ROLE", "solo")
    now = time.time()

    with _db_lock, get_db() as db:
        existing = db.execute(
            "SELECT node_id FROM nodes WHERE node_id=?", (node_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE nodes SET role=?,ip=?,port=?,last_seen=?,online=1"
                " WHERE node_id=?",
                (role, "127.0.0.1", 8080, now, node_id),
            )
        else:
            db.execute(
                "INSERT INTO nodes"
                "(node_id,role,ip,port,registered_at,last_seen,online)"
                " VALUES(?,?,?,?,?,?,1)",
                (node_id, role, "127.0.0.1", 8080, now, now),
            )
        db.execute(
            "INSERT INTO events(ts,node_id,event_type,detail) VALUES(?,?,?,?)",
            (now, node_id, "registered", "solo self-registration"),
        )
        db.commit()
    log.info("Self-registered as node_id=%s role=%s", node_id, role)


###############################################################################
# Self-heartbeat thread
###############################################################################


def self_heartbeat():
    node_id = "solo-node"
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                if line.startswith("NODE_ID="):
                    node_id = line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass

    while True:
        time.sleep(30)
        with _db_lock, get_db() as db:
            db.execute(
                "UPDATE nodes SET last_seen=?, online=1 WHERE node_id=?",
                (time.time(), node_id),
            )
            db.commit()


###############################################################################
# System metrics
###############################################################################


def read_cpu_percent():
    """Two-sample CPU usage via /proc/stat."""
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:]))
        idle = vals[3]
        total = sum(vals)
        time.sleep(0.2)
        with open("/proc/stat") as f:
            line = f.readline()
        vals2 = list(map(int, line.split()[1:]))
        idle2 = vals2[3]
        total2 = sum(vals2)
        delta_total = total2 - total
        delta_idle = idle2 - idle
        if delta_total == 0:
            return 0.0
        return round(100.0 * (delta_total - delta_idle) / delta_total, 1)
    except Exception:
        return None


def read_mem():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        used = total - avail
        pct = round(100.0 * used / total, 1) if total else 0
        return {"total_mb": total // 1024, "used_mb": used // 1024, "percent": pct}
    except Exception:
        return None


def read_disk():
    try:
        import shutil

        path = "/data/phonecluster" if os.path.exists("/data/phonecluster") else "/"
        usage = shutil.disk_usage(path)
        return {
            "total_gb": round(usage.total / 1e9, 1),
            "used_gb": round(usage.used / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "percent": round(100.0 * usage.used / usage.total, 1),
        }
    except Exception:
        return None


###############################################################################
# Flask app
###############################################################################

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": time.time()})


@app.route("/register", methods=["POST"])
@require_api_key
def register():
    data = request.get_json(force=True, silent=True) or {}
    node_id = data.get("node_id")
    role = data.get("role")
    ip = data.get("ip") or request.remote_addr
    port = int(data.get("port", 8080))
    meta = str(data.get("meta", ""))

    if not node_id or not role:
        abort(400, "node_id and role required")

    now = time.time()
    with _db_lock, get_db() as db:
        exists = db.execute(
            "SELECT node_id FROM nodes WHERE node_id=?", (node_id,)
        ).fetchone()
        if exists:
            db.execute(
                "UPDATE nodes SET role=?,ip=?,port=?,last_seen=?,online=1,meta=?"
                " WHERE node_id=?",
                (role, ip, port, now, meta, node_id),
            )
            ev = "re-registered"
        else:
            db.execute(
                "INSERT INTO nodes"
                "(node_id,role,ip,port,registered_at,last_seen,online,meta)"
                " VALUES(?,?,?,?,?,?,1,?)",
                (node_id, role, ip, port, now, now, meta),
            )
            ev = "registered"
        db.execute(
            "INSERT INTO events(ts,node_id,event_type,detail) VALUES(?,?,?,?)",
            (now, node_id, ev, f"ip={ip} port={port}"),
        )
        db.commit()
    return jsonify({"status": "ok", "node_id": node_id, "event": ev})


@app.route("/heartbeat", methods=["POST"])
@require_api_key
def heartbeat():
    data = request.get_json(force=True, silent=True) or {}
    node_id = data.get("node_id")
    if not node_id:
        abort(400, "node_id required")
    now = time.time()
    with _db_lock, get_db() as db:
        row = db.execute(
            "SELECT node_id FROM nodes WHERE node_id=?", (node_id,)
        ).fetchone()
        if not row:
            abort(404, f"Unknown node: {node_id}")
        db.execute(
            "UPDATE nodes SET last_seen=?,online=1 WHERE node_id=?", (now, node_id)
        )
        db.commit()
    return jsonify({"status": "ok", "ts": now})


@app.route("/nodes")
@require_api_key
def nodes():
    with _db_lock, get_db() as db:
        rows = db.execute("SELECT * FROM nodes ORDER BY registered_at").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/status")
@require_api_key
def status():
    with _db_lock, get_db() as db:
        all_nodes = db.execute("SELECT * FROM nodes ORDER BY registered_at").fetchall()
        online = db.execute(
            "SELECT COUNT(*) c FROM nodes WHERE online=1"
        ).fetchone()["c"]
        offline = db.execute(
            "SELECT COUNT(*) c FROM nodes WHERE online=0"
        ).fetchone()["c"]
        evs = db.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT 30"
        ).fetchall()
    return jsonify({
        "coordinator": {"ts": time.time(), "version": "1.0.0-solo"},
        "summary": {"total": online + offline, "online": online, "offline": offline},
        "nodes": [dict(n) for n in all_nodes],
        "events": [dict(e) for e in evs],
    })


@app.route("/metrics/json")
@require_api_key
def metrics_json():
    """Lightweight system snapshot for the dashboard."""
    return jsonify({
        "ts": time.time(),
        "cpu": {"percent": read_cpu_percent()},
        "mem": read_mem(),
        "disk": read_disk(),
    })


@app.route("/events")
@require_api_key
def events():
    limit = min(int(request.args.get("limit", 50)), 500)
    with _db_lock, get_db() as db:
        rows = db.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


###############################################################################
# Entry point
###############################################################################

if __name__ == "__main__":
    init_db()
    self_register()
    threading.Thread(target=sweeper, daemon=True).start()
    threading.Thread(target=self_heartbeat, daemon=True).start()
    log.info("PhoneCluster coordinator (solo) on port %d", PORT)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
