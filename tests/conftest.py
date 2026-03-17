"""
tests/conftest.py
Shared pytest fixtures available to all test modules.
"""

import os
import pytest

# Ensure env vars are set before any test module imports coordinator
os.environ.setdefault("PC_API_KEY",          "test-api-key-ci")
os.environ.setdefault("PC_COORDINATOR_PORT", "7777")
os.environ.setdefault("NODE_ID",             "ci-node")
os.environ.setdefault("NODE_ROLE",           "solo")


@pytest.fixture(scope="session")
def base_url():
    return os.environ.get("COORDINATOR_BASE_URL", "http://127.0.0.1:7777")


@pytest.fixture(scope="session")
def api_key():
    return os.environ.get("PC_API_KEY", "test-api-key-ci")


@pytest.fixture(scope="session")
def auth_headers(api_key):
    return {"X-API-Key": api_key, "Content-Type": "application/json"}
