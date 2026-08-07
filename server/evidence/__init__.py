"""Post-scan evidence collection and state computation.

After scanners finish, findings are mapped to FRs via the evidence-mapping
pack, producing Evidence rows. FR states are then computed and cached in
`fr_state` using the 8-state resolver.
"""
from server.evidence.collector import collect_evidence_from_findings
from server.evidence.state_compute import compute_states_for_run

__all__ = ["collect_evidence_from_findings", "compute_states_for_run"]
