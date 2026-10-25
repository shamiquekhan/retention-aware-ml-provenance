"""Metrics for synthetic retention-plan evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .graph import EvidenceGraph
from .planner import DecisionPlan
from .schema import InventorySnapshot


@dataclass(frozen=True)
class BenchmarkMetrics:
    releases: int
    required_objects: int
    current_complete_releases: int
    planned_complete_releases: int
    retention_gap_releases: int
    unsafe_deletion_proposals: int
    deletion_decisions: int
    retained_bytes: int
    required_bytes: int
    retention_overhead_bytes: int
    planned_retention_byte_days: int
    minimum_required_byte_days: int
    retention_overhead_byte_days: int
    earliest_gap_lead_time_days: int | None
    api_requests: int
    failed_requests: int
    unknown_objects: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "releases": self.releases,
            "required_objects": self.required_objects,
            "current_evidence_chain_completeness": _rate(self.current_complete_releases, self.releases),
            "planned_evidence_chain_completeness": _rate(self.planned_complete_releases, self.releases),
            "retention_gap_incidence": _rate(self.retention_gap_releases, self.releases),
            "unsafe_deletion_proposal_rate": _rate(self.unsafe_deletion_proposals, self.deletion_decisions),
            "retained_bytes": self.retained_bytes,
            "required_bytes": self.required_bytes,
            "retention_overhead_bytes": self.retention_overhead_bytes,
            "planned_retention_byte_days": self.planned_retention_byte_days,
            "minimum_required_byte_days": self.minimum_required_byte_days,
            "retention_overhead_byte_days": self.retention_overhead_byte_days,
            "earliest_gap_lead_time_days": self.earliest_gap_lead_time_days,
            "api_requests": self.api_requests,
            "failed_requests": self.failed_requests,
            "unknown_objects": self.unknown_objects,
            "inventory_coverage": _rate(self.api_requests - self.failed_requests, self.api_requests),
        }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def evaluate_plan(snapshot: InventorySnapshot, plan: DecisionPlan) -> BenchmarkMetrics:
    objects = snapshot.object_map()
    graph = EvidenceGraph(snapshot)
    closures = graph.closures_for_releases()
    action_map = {action.object_id: action for action in plan.actions}
    current_complete = 0
    planned_complete = 0
    gap_releases = 0
    gap_leads: list[int] = []
    required_objects: set[str] = set()
    required_horizons: dict[str, datetime] = {}

    for release in snapshot.releases:
        closure = closures[release.release_id]
        required_objects.update(closure.required_ids)
        for object_id in closure.required_ids:
            required_horizons[object_id] = max(
                required_horizons.get(object_id, release.audit_horizon),
                release.audit_horizon,
            )
        complete_now = not closure.missing_ids
        complete_planned = not closure.missing_ids
        release_has_gap = bool(closure.missing_ids)
        for object_id in closure.required_ids:
            obj = objects.get(object_id)
            if obj is None:
                complete_now = False
                complete_planned = False
                release_has_gap = True
                continue
            if not obj.archive_verified() and not obj.survives_until(release.audit_horizon):
                complete_now = False
                release_has_gap = True
                if obj.expires_at is None:
                    gap_leads.append(0)
                else:
                    gap_leads.append((obj.expires_at - snapshot.now).days)
            action = action_map.get(object_id)
            if action is None or action.action in {"ARCHIVE", "HOLD_FOR_REVIEW"}:
                complete_planned = False
        current_complete += int(complete_now)
        planned_complete += int(complete_planned)
        gap_releases += int(release_has_gap)

    deletion_decisions = [
        action for action in plan.actions if action.action == "CANDIDATE_FOR_DELETION"
    ]
    unsafe = [
        action
        for action in deletion_decisions
        if action.object_id in required_objects
        or (objects.get(action.object_id) is not None and objects[action.object_id].protected)
    ]
    retained = [
        action
        for action in plan.actions
        if action.action in {"PRESERVE", "PRESERVE_DEPENDENCY", "ARCHIVE", "HOLD_FOR_REVIEW"}
    ]
    retained_bytes = sum(
        objects[action.object_id].size_bytes or 0
        for action in retained
        if action.object_id in objects
    )
    required_bytes = sum(
        objects[object_id].size_bytes or 0
        for object_id in required_objects
        if object_id in objects
    )
    planned_retention_byte_days = 0
    minimum_required_byte_days = 0
    workload_horizon = max((release.audit_horizon for release in snapshot.releases), default=snapshot.now)
    for object_id, obj in objects.items():
        size = obj.size_bytes or 0
        if object_id in required_horizons:
            days = max(0, (required_horizons[object_id] - snapshot.now).days)
            minimum_required_byte_days += size * days
        action = action_map.get(object_id)
        if action and action.action in {"PRESERVE", "PRESERVE_DEPENDENCY", "ARCHIVE", "HOLD_FOR_REVIEW"}:
            days = max(0, (required_horizons.get(object_id, workload_horizon) - snapshot.now).days)
            planned_retention_byte_days += size * days

    return BenchmarkMetrics(
        releases=len(snapshot.releases),
        required_objects=len(required_objects),
        current_complete_releases=current_complete,
        planned_complete_releases=planned_complete,
        retention_gap_releases=gap_releases,
        unsafe_deletion_proposals=len(unsafe),
        deletion_decisions=len(deletion_decisions),
        retained_bytes=retained_bytes,
        required_bytes=required_bytes,
        retention_overhead_bytes=max(0, retained_bytes - required_bytes),
        planned_retention_byte_days=planned_retention_byte_days,
        minimum_required_byte_days=minimum_required_byte_days,
        retention_overhead_byte_days=max(
            0, planned_retention_byte_days - minimum_required_byte_days
        ),
        earliest_gap_lead_time_days=min(gap_leads) if gap_leads else None,
        api_requests=snapshot.api_requests,
        failed_requests=snapshot.failed_requests,
        unknown_objects=snapshot.unknown_objects,
    )
