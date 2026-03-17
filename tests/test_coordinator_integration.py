"""
tests/test_coordinator_integration.py
Integration tests - coordinator must be running on 127.0.0.1:7777 before these run.
The CI workflow starts it in a background step.
"""

import os
import time
import requests

BASE    = os.environ.get("COORDINATOR_BASE_URL", "http://127.0.0.1:7777")
API_KEY = os.environ.get("PC_API_KEY", "test-api-key-ci")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

###############################################################################
# Helpers
###############################################################################

def post(path, payload):
    return requests.post(f"{BASE}{path}", json=payload, headers=HEADERS, timeout=5)

def get(path):
    return requests.get(f"{BASE}{path}", headers=HEADERS, timeout=5)

###############################################################################
# Health
###############################################################################

class TestHealth:
    def test_health_returns_ok(self):
        r = requests.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "ts" in body

    def test_health_no_auth_required(self):
        """Health endpoint must work without an API key."""
        r = requests.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200

###############################################################################
# Auth
###############################################################################

class TestAuth:
    def test_status_requires_api_key(self):
        r = requests.get(f"{BASE}/status", timeout=5)
        assert r.status_code == 401

    def test_wrong_api_key_rejected(self):
        r = requests.get(f"{BASE}/status",
                         headers={"X-API-Key": "wrong-key"}, timeout=5)
        assert r.status_code == 401

    def test_correct_api_key_accepted(self):
        r = get("/status")
        assert r.status_code == 200

    def test_api_key_via_query_param(self):
        r = requests.get(f"{BASE}/status?api_key={API_KEY}", timeout=5)
        assert r.status_code == 200

###############################################################################
# Registration
###############################################################################

class TestRegister:
    def test_register_new_node(self):
        r = post("/register", {
            "node_id": "integ-node-1",
            "role":    "solo",
            "ip":      "192.168.1.10",
            "port":    8080,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"]  == "ok"
        assert body["node_id"] == "integ-node-1"
        assert body["event"]   == "registered"

    def test_register_same_node_twice_is_reregistered(self):
        payload = {"node_id": "integ-node-dup", "role": "solo", "ip": "192.168.1.11", "port": 8080}
        post("/register", payload)
        r = post("/register", payload)
        assert r.status_code == 200
        assert r.json()["event"] == "re-registered"

    def test_register_missing_node_id_rejected(self):
        r = post("/register", {"role": "solo"})
        assert r.status_code == 400

    def test_register_missing_role_rejected(self):
        r = post("/register", {"node_id": "orphan"})
        assert r.status_code == 400

    def test_register_node_appears_in_nodes_list(self):
        post("/register", {"node_id": "integ-listed", "role": "nas", "ip": "192.168.1.20", "port": 8080})
        r = get("/nodes")
        assert r.status_code == 200
        ids = [n["node_id"] for n in r.json()]
        assert "integ-listed" in ids

###############################################################################
# Heartbeat
###############################################################################

class TestHeartbeat:
    def setup_method(self):
        post("/register", {
            "node_id": "hb-node",
            "role":    "solo",
            "ip":      "192.168.1.30",
            "port":    8080,
        })

    def test_heartbeat_accepted(self):
        r = post("/heartbeat", {"node_id": "hb-node"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "ts" in body

    def test_heartbeat_unknown_node_rejected(self):
        r = post("/heartbeat", {"node_id": "ghost-node-xyz"})
        assert r.status_code == 404

    def test_heartbeat_updates_last_seen(self):
        t_before = time.time()
        time.sleep(0.1)
        post("/heartbeat", {"node_id": "hb-node"})
        nodes = get("/nodes").json()
        node  = next(n for n in nodes if n["node_id"] == "hb-node")
        assert node["last_seen"] > t_before

    def test_heartbeat_marks_node_online(self):
        post("/heartbeat", {"node_id": "hb-node"})
        nodes = get("/nodes").json()
        node  = next(n for n in nodes if n["node_id"] == "hb-node")
        assert node["online"] == 1

###############################################################################
# Status
###############################################################################

class TestStatus:
    def test_status_shape(self):
        r = get("/status")
        assert r.status_code == 200
        body = r.json()
        assert "coordinator" in body
        assert "summary"     in body
        assert "nodes"       in body
        assert "events"      in body

    def test_status_summary_counts(self):
        # Register a fresh node to ensure at least one online node
        post("/register", {"node_id": "count-node", "role": "solo",
                           "ip": "10.0.0.1", "port": 8080})
        body   = get("/status").json()
        summary = body["summary"]
        assert summary["total"]  == summary["online"] + summary["offline"]
        assert summary["online"] >= 1

    def test_coordinator_version_present(self):
        body = get("/status").json()
        assert "version" in body["coordinator"]

###############################################################################
# Events
###############################################################################

class TestEvents:
    def test_events_endpoint_returns_list(self):
        r = get("/events")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_registration_creates_event(self):
        post("/register", {"node_id": "ev-node", "role": "solo",
                           "ip": "10.0.0.2", "port": 8080})
        events = get("/events").json()
        ev = next((e for e in events if e["node_id"] == "ev-node"), None)
        assert ev is not None
        assert ev["event_type"] == "registered"

    def test_events_limit_param(self):
        r = requests.get(f"{BASE}/events?limit=2", headers=HEADERS, timeout=5)
        assert r.status_code == 200
        assert len(r.json()) <= 2
