"""Planning Studio constants shared by atomic/workflow modules."""
from __future__ import annotations

PLANNING_STATES = {
    "draft",
    "recommendations_ready",
    "review_required",
    "approved",
    "superseded",
    "rejected",
}

BLUEPRINT_DECISIONS = {
    "pending_review",
    "accepted_as_is",
    "tailored",
    "rejected",
    "not_applicable",
}

HANDOFF_ALLOWED_STATES = {"approved"}

