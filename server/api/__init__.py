"""HTTP API layer.

Routes are split by resource (health, scans, findings). Pydantic schemas
live in `schemas/` and serve as the contract between the API and the
frontend/agent.
"""
