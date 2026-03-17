"""
tests/test_metrics.py
Tests for the /metrics/json endpoint - verifies shape, types, and plausible ranges.
Coordinator must be running before these run.
"""

import os
import requests

BASE    = os.environ.get("COORDINATOR_BASE_URL", "http://127.0.0.1:7777")
API_KEY = os.environ.get("PC_API_KEY", "test-api-key-ci")
HEADERS = {"X-API-Key": API_KEY}

def get_metrics():
    return requests.get(f"{BASE}/metrics/json", headers=HEADERS, timeout=10).json()

###############################################################################

class TestMetricsShape:
    def test_returns_200(self):
        r = requests.get(f"{BASE}/metrics/json", headers=HEADERS, timeout=10)
        assert r.status_code == 200

    def test_top_level_keys(self):
        m = get_metrics()
        assert "ts"   in m
        assert "cpu"  in m
        assert "mem"  in m
        assert "disk" in m

    def test_ts_is_recent(self):
        import time
        m = get_metrics()
        assert abs(m["ts"] - time.time()) < 10  # within 10s of now

class TestCPUMetrics:
    def test_cpu_key_present(self):
        m = get_metrics()
        assert "percent" in m["cpu"]

    def test_cpu_percent_in_range(self):
        m = get_metrics()
        pct = m["cpu"]["percent"]
        if pct is not None:
            assert 0.0 <= pct <= 100.0

class TestMemMetrics:
    def test_mem_keys(self):
        m = get_metrics()
        mem = m["mem"]
        assert mem is not None
        for key in ("total_mb", "used_mb", "percent"):
            assert key in mem, f"Missing mem key: {key}"

    def test_mem_values_plausible(self):
        m   = get_metrics()
        mem = m["mem"]
        assert mem["total_mb"] > 0
        assert mem["used_mb"]  >= 0
        assert mem["used_mb"]  <= mem["total_mb"]
        assert 0.0 <= mem["percent"] <= 100.0

    def test_mem_percent_consistent(self):
        """percent should match used/total within floating point tolerance."""
        m   = get_metrics()
        mem = m["mem"]
        expected_pct = round(100.0 * mem["used_mb"] / mem["total_mb"], 1)
        assert abs(mem["percent"] - expected_pct) <= 1.0

class TestDiskMetrics:
    def test_disk_keys(self):
        m    = get_metrics()
        disk = m["disk"]
        assert disk is not None
        for key in ("total_gb", "used_gb", "free_gb", "percent"):
            assert key in disk, f"Missing disk key: {key}"

    def test_disk_values_plausible(self):
        m    = get_metrics()
        disk = m["disk"]
        assert disk["total_gb"] > 0
        assert disk["used_gb"]  >= 0
        assert disk["free_gb"]  >= 0
        assert 0.0 <= disk["percent"] <= 100.0

    def test_disk_used_plus_free_approx_total(self):
        """used + free should be within 5% of total (reserved blocks account for the gap)."""
        m    = get_metrics()
        disk = m["disk"]
        approx = disk["used_gb"] + disk["free_gb"]
        assert abs(approx - disk["total_gb"]) / disk["total_gb"] < 0.05
