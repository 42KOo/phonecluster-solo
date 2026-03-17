"""
tests/test_coordinator_unit.py
Unit tests for coordinator.py — no server needed, tests functions directly.
"""

import os
import sys
import time
import tempfile
import sqlite3
import pytest

# Point the coordinator at a temp DB for each test
os.environ.setdefault("PC_API_KEY",           "test-api-key-ci")
os.environ.setdefault("PC_COORDINATOR_PORT",  "7777")

# Inject coordinator module path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

###############################################################################
# Fixtures
###############################################################################

@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """Give each test its own isolated SQLite database."""
    db_file = str(tmp_path / "test.db")
    os.environ["PC_DB_PATH"] = db_file
    # Re-import so the module picks up the new DB path
    import importlib
    import coordinator.coordinator as coord
    importlib.reload(coord)
    coord.init_db()
    yield coord
    # cleanup handled by tmp_path fixture

###############################################################################
# DB init
###############################################################################

class TestDBInit:
    def test_tables_created(self, tmp_db):
        conn = sqlite3.connect(os.environ["PC_DB_PATH"])
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "nodes"  in tables
        assert "events" in tables

###############################################################################
# Registration logic
###############################################################################

class TestSelfRegister:
    def test_self_register_creates_node(self, tmp_db, tmp_path):
        """self_register() should insert a node row."""
        config = tmp_path / "config.env"
        config.write_text("NODE_ID=test-solo\nNODE_ROLE=solo\n")

        import unittest.mock as mock
        with mock.patch("builtins.open", mock.mock_open(read_data=config.read_text())):
            tmp_db.self_register()

        conn = sqlite3.connect(os.environ["PC_DB_PATH"])
        row = conn.execute("SELECT * FROM nodes WHERE node_id='test-solo'").fetchone()
        assert row is not None

    def test_self_register_idempotent(self, tmp_db, tmp_path):
        """Calling self_register() twice should not error or duplicate the node."""
        config = tmp_path / "config.env"
        config.write_text("NODE_ID=test-solo\nNODE_ROLE=solo\n")

        import unittest.mock as mock
        with mock.patch("builtins.open", mock.mock_open(read_data=config.read_text())):
            tmp_db.self_register()
            tmp_db.self_register()

        conn = sqlite3.connect(os.environ["PC_DB_PATH"])
        count = conn.execute("SELECT COUNT(*) FROM nodes WHERE node_id='test-solo'").fetchone()[0]
        assert count == 1

###############################################################################
# Metrics readers
###############################################################################

class TestMetricsReaders:
    def test_read_mem_returns_dict(self, tmp_db):
        result = tmp_db.read_mem()
        assert result is not None
        assert "total_mb" in result
        assert "used_mb"  in result
        assert "percent"  in result
        assert 0 <= result["percent"] <= 100

    def test_read_disk_returns_dict(self, tmp_db):
        result = tmp_db.read_disk()
        assert result is not None
        assert "total_gb" in result
        assert "used_gb"  in result
        assert "free_gb"  in result
        assert "percent"  in result
        assert result["total_gb"] > 0

    def test_read_cpu_returns_number(self, tmp_db):
        result = tmp_db.read_cpu_percent()
        # May be None on unusual CI environments but should not raise
        if result is not None:
            assert 0.0 <= result <= 100.0

###############################################################################
# Sweeper logic
###############################################################################

class TestSweeper:
    def _insert_node(self, node_id, last_seen_offset=0, online=1):
        """Insert a node directly into the test DB."""
        conn = sqlite3.connect(os.environ["PC_DB_PATH"])
        now = time.time() + last_seen_offset
        conn.execute("""
            INSERT OR REPLACE INTO nodes
            (node_id, role, ip, port, registered_at, last_seen, online)
            VALUES (?, 'solo', '127.0.0.1', 8080, ?, ?, ?)
        """, (node_id, now, now, online))
        conn.commit()

    def test_fresh_node_stays_online(self, tmp_db):
        """A node that just heartbeated should not be marked offline."""
        self._insert_node("fresh-node", last_seen_offset=0)
        # Simulate one sweep with a very long TTL
        cutoff = time.time() - 9999
        conn = sqlite3.connect(os.environ["PC_DB_PATH"])
        gone = conn.execute(
            "SELECT node_id FROM nodes WHERE online=1 AND last_seen < ?", (cutoff,)
        ).fetchall()
        assert len(gone) == 0

    def test_stale_node_detected(self, tmp_db):
        """A node with last_seen > TTL ago should be detected by the sweeper query."""
        self._insert_node("stale-node", last_seen_offset=-200)  # 200s ago
        TTL = 90
        cutoff = time.time() - TTL
        conn = sqlite3.connect(os.environ["PC_DB_PATH"])
        gone = conn.execute(
            "SELECT node_id FROM nodes WHERE online=1 AND last_seen < ?", (cutoff,)
        ).fetchall()
        assert any(r[0] == "stale-node" for r in gone)
