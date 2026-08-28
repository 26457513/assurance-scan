"""Scan execution layer.

Composition:
  - `scanners.py`   — declarative per-scanner configuration
  - `parsers/`      — per-scanner output parsers (semgrep, trivy, ...)
  - `runner.py`     — spawns scanner containers via the docker CLI
  - `orchestrator.py` — drives one scan end-to-end (queue -> DB)
  - `queue.py`      — in-process async scan queue
"""
