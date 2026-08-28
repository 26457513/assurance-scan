"""Atomic repositories. One class per table; small methods; no cross-table logic.

For multi-table operations use a service-layer class (e.g. ScanOrchestrator)
that composes repositories inside a single transaction.
"""
