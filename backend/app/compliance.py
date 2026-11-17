"""Bounded security-control checks; results do not establish SOC 2 compliance."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from app.models import SecurityEvent
from app.schemas import ControlResultOut
from app.security_evidence import DENIAL_THRESHOLD, DENIAL_WINDOW_MINUTES

PRIVILEGED_ACTIONS = {
    "booking.approve", "booking.cancel", "booking.execute", "connector.configure", "security.read",
}
AUDIT_TABLES = {"security_event", "booking_transition", "execution_event", "compliance_assessment"}


@dataclass
class _ControlTally:
    """Routes each classified subject to the failed/missing lists and collects its evidence."""
    failed: list[int] = field(default_factory=list)
    missing: list[int] = field(default_factory=list)
    evidence: set[int] = field(default_factory=set)

    def record(self, outcome: str, subject_id: int, evidence_events: list[SecurityEvent]) -> None:
        if outcome == "fail":
            self.failed.append(subject_id)
        elif outcome == "missing":
            self.missing.append(subject_id)
        self.evidence.update(event.id for event in evidence_events if event.id is not None)

    def status(self, *, had_subjects: bool) -> Literal["pass", "fail", "insufficient_evidence"]:
        if self.failed:
            return "fail"
        return "insufficient_evidence" if self.missing or not had_subjects else "pass"


def _mfa_proof_matches(success: SecurityEvent, admission: SecurityEvent) -> bool:
    """A verified MFA step that belongs to the same session/actor/tenant and precedes the admission."""
    return (
        success.action == "auth.mfa.verify"
        and success.decision == "allow"
        and success.policy_version == "1"
        and success.mfa_verified is True
        and _same_admission_subject(success, admission)
        and success.created_at <= admission.created_at
    )


def _same_admission_subject(success: SecurityEvent, admission: SecurityEvent) -> bool:
    return (
        admission.actor_user_id is not None
        and success.session_id is not None
        and success.session_id == admission.session_id
        and success.actor_user_id == admission.actor_user_id
        and success.tenant_id == admission.tenant_id
    )


def _classify_privileged_admission(
    event: SecurityEvent, successes: list[SecurityEvent]
) -> tuple[str, list[SecurityEvent]]:
    """Classify one privileged admission as 'pass'/'fail'/'missing' and return its MFA evidence."""
    if event.policy_version != "1":
        return "missing", []
    inputs = (event.enforcement_active, event.mfa_required, event.mfa_verified)
    if False in inputs:
        return "fail", []
    if None in inputs:
        return "missing", []
    verified = [success for success in successes if _mfa_proof_matches(success, event)]
    return ("missing" if not verified else "pass"), verified


def evaluate_mfa(events: list[SecurityEvent], successes: list[SecurityEvent]) -> ControlResultOut:
    allowed = [event for event in events if event.action in PRIVILEGED_ACTIONS and event.decision == "allow"]
    tally = _ControlTally(evidence={event.id for event in allowed if event.id is not None})
    for event in allowed:
        assert event.id is not None
        outcome, verified = _classify_privileged_admission(event, successes)
        tally.record(outcome, event.id, verified)
    status = tally.status(had_subjects=bool(allowed))
    return ControlResultOut(
        control="privileged_mfa", status=status,
        summary=f"{len(allowed)} privileged admissions; {len(tally.failed)} violations; {len(tally.missing)} missing MFA evidence.",
        evidence_event_ids=sorted(tally.evidence),
        details={"violation_event_ids": tally.failed, "missing_evidence_event_ids": tally.missing},
    )


def _revocation_contains_denial(
    revocation: SecurityEvent, denial: SecurityEvent, window: deque[SecurityEvent]
) -> bool:
    """A revocation that answers this denial: same tenant/device, enforced, within 60s, and
    citing at least DENIAL_THRESHOLD of the window's denials including this one."""
    related = set(revocation.related_event_ids or [])
    return bool(
        _same_denial_scope(revocation, denial)
        and _within_containment_window(revocation, denial)
        and denial.id in related
        and _contains_threshold_denials(window, related)
    )


def _same_denial_scope(revocation: SecurityEvent, denial: SecurityEvent) -> bool:
    return (
        revocation.tenant_id == denial.tenant_id
        and revocation.device_id == denial.device_id
        and revocation.policy_version == "1"
        and revocation.enforcement_active is True
    )


def _within_containment_window(revocation: SecurityEvent, denial: SecurityEvent) -> bool:
    deadline = denial.created_at + timedelta(seconds=60)
    return denial.created_at <= revocation.created_at <= deadline


def _contains_threshold_denials(window: deque[SecurityEvent], related: set[int]) -> bool:
    return len({event.id for event in window} & related) >= DENIAL_THRESHOLD


def _containment_inputs_incomplete(event: SecurityEvent) -> bool:
    return event.policy_version != "1" or event.session_id is None or event.enforcement_active is None


def _classify_threshold_crossing(
    event: SecurityEvent,
    window: deque[SecurityEvent],
    revocations: dict[str, list[SecurityEvent]],
    window_end: datetime,
) -> tuple[str, list[SecurityEvent]]:
    """Classify a denial that crossed the threshold as 'pass'/'fail'/'missing' with revocation evidence."""
    if _containment_inputs_incomplete(event):
        return "missing", []
    assert event.session_id is not None  # guaranteed by _containment_inputs_incomplete
    if event.enforcement_active is False:
        return "fail", []
    matched = [
        revocation for revocation in revocations[event.session_id]
        if _revocation_contains_denial(revocation, event, window)
    ]
    if matched:
        return "pass", matched
    deadline = event.created_at + timedelta(seconds=60)
    return ("missing" if deadline > window_end else "fail"), []


def _denial_crosses_threshold(
    event: SecurityEvent,
    windows: dict[tuple[str, str, str | None], deque[SecurityEvent]],
    window_start: datetime | None,
) -> deque[SecurityEvent] | None:
    """Add a denial to its per-session sliding window; return the window if it just crossed the
    containment threshold within scope, else None."""
    window = windows[(event.tenant_id, event.device_id, event.session_id)]
    since = event.created_at - timedelta(minutes=DENIAL_WINDOW_MINUTES)
    while window and window[0].created_at < since:
        window.popleft()
    window.append(event)
    if len(window) < DENIAL_THRESHOLD:
        return None
    if window_start is not None and event.created_at < window_start:
        return None
    return window


def _is_session_revocation(event: SecurityEvent) -> bool:
    return bool(event.action == "session.revoke" and event.session_id and event.decision == "allow")


def _index_revocations_by_session(events: list[SecurityEvent]) -> dict[str, list[SecurityEvent]]:
    revocations: dict[str, list[SecurityEvent]] = defaultdict(list)
    for event in events:
        if _is_session_revocation(event):
            assert event.session_id is not None
            revocations[event.session_id].append(event)
    return revocations


def evaluate_containment(
    events: list[SecurityEvent], window_end: datetime, window_start: datetime | None = None,
) -> ControlResultOut:
    windows: dict[tuple[str, str, str | None], deque[SecurityEvent]] = defaultdict(deque)
    revocations = _index_revocations_by_session(events)
    tally = _ControlTally()
    triggered = 0
    for event in sorted(events, key=lambda item: (item.created_at, item.id or 0)):
        if event.decision != "deny":
            continue
        window = _denial_crosses_threshold(event, windows, window_start)
        if window is None:
            continue
        assert event.id is not None
        triggered += 1
        tally.evidence.update(denial.id for denial in window if denial.id is not None)
        outcome, matched = _classify_threshold_crossing(event, window, revocations, window_end)
        tally.record(outcome, event.id, matched)
    status = tally.status(had_subjects=bool(triggered))
    return ControlResultOut(
        control="session_containment", status=status,
        summary=f"{triggered} threshold crossings; {len(tally.failed)} containment violations; {len(tally.missing)} unresolved.",
        evidence_event_ids=sorted(tally.evidence),
        details={"violation_event_ids": tally.failed, "missing_evidence_event_ids": tally.missing, "response_seconds": 60},
    )


def _audit_protection_failed(row: dict[str, Any]) -> bool:
    return not row["mutation_blocked"] or not row["truncate_blocked"] or row["can_bypass"]


def evaluate_audit_protections(protections: list[dict[str, Any]]) -> ControlResultOut:
    present = {row["table_name"] for row in protections}
    missing = sorted(AUDIT_TABLES - present)
    failed = [row["table_name"] for row in protections if _audit_protection_failed(row)]
    status = "fail" if failed else "insufficient_evidence" if missing else "pass"
    return ControlResultOut(
        control="audit_protections", status=status,
        summary="Current trigger configuration and application-role privileges; historical integrity is not evaluated.",
        details={"tables": protections, "missing_tables": missing, "failed_tables": failed},
    )
