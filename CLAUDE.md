# PhoneCluster Solo

Single-phone mini-cloud on Android via Termux + proot-distro (Arch Linux ARM).

## Stack
- coordinator/coordinator.py — Flask + SQLite REST API, port 7777
- config/Caddyfile.solo — Caddy reverse proxy, ports 8080 + 7000
- services/*/run — s6 service definitions
- dashboard/index.html — single-file vanilla JS dashboard

## CI
- .github/workflows/ci.yml — ruff check, caddy validate, html-validate, pytest
- Coordinator tests: tests/test_coordinator_{unit,integration}.py + test_metrics.py
- E2E: tests/e2e.sh (requires coordinator running on 127.0.0.1:7777)

## Key constraints
- Caddyfile must be ASCII-only (no unicode)
- coordinator.py must pass: ruff check (E, F, W, I rules, line-length=100)
- dashboard/index.html must pass html-validate:recommended
- All <button> need type=, all <input> need autocomplete=, no heading level skips
