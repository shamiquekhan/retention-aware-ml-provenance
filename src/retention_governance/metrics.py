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
    planned_resolution_releases: int
    gap_objects: int
    resolved_gap_objects: int
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
    known_size_objects: int
    sized_objects: int
    _collection_complete: int
    _collection_categories: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "releases": self.releases,
            "required_objects": self.required_objects,
            "current_evidence_chain_completeness": _rate(self.current_complete_releases, self.releases),
            "planned_evidence_chain_completeness": _rate(self.planned_complete_releases, self.releases),
            "verified_projected_evidence_chain_completeness": _rate(
                self.planned_complete_releases, self.releases
            ),
            "planned_resolution_coverage": _rate(self.planned_resolution_releases, self.releases),
            "gap_resolution_coverage": _rate(self.resolved_gap_objects, self.gap_objects),
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
            "request_success_rate": _rate(self.api_requests - self.failed_requests, self.api_requests),
            "inventory_coverage": _rate(self.collection_complete, self.collection_categories),
            "known_size_coverage": _rate(self.known_size_objects, self.sized_objects),
        }

    @property
    def collection_complete(self) -> int:
        return self._collection_complete

    @property
    def collection_categories(self) -> int:
        return self._collection_categories


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
    planned_resolution_releases = 0
    gap_objects: set[str] = set()
    resolved_gap_objects: set[str] = set()
    gap_releases = 0
    gap_leads: list[int] = []
    required_objects: set[str] = set()
    required_horizons: dict[str, datetime] = {}
    inventory_complete = snapshot.collection_status == "complete" and all(
        status == "complete" for _, status in snapshot.collection_states
    )

    for release in snapshot.releases:
        closure = closures[release.release_id]
        required_objects.update(closure.required_ids)
        for object_id in closure.required_ids:
            required_horizons[object_id] = max(
                required_horizons.get(object_id, release.audit_horizon),
                release.audit_horizon,
            )
        complete_now = inventory_complete and not closure.missing_ids
        complete_planned = inventory_complete and not closure.missing_ids
        release_has_gap = bool(closure.missing_ids) or not inventory_complete
        release_gaps: set[str] = set(closure.missing_ids)
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
                release_gaps.add(object_id)
                if obj.expires_at is None:
                    gap_leads.append(0)
                else:
                    gap_leads.append((obj.expires_at - snapshot.now).days)
            action = action_map.get(object_id)
            if action is None or action.action in {
                "ARCHIVE",
                "HOLD_FOR_REVIEW",
                "CANDIDATE_FOR_DELETION",
            }:
                complete_planned = False
            elif not obj.archive_verified() and not obj.survives_until(release.audit_horizon):
                complete_planned = False
        gap_objects.update(release_gaps)
        resolved_gap_objects.update(
            object_id
            for object_id in release_gaps
            if action_map.get(object_id) is not None
            and action_map[object_id].action == "ARCHIVE"
        )
        if release_gaps and all(
            action_map.get(object_id) is not None
            and action_map[object_id].action == "ARCHIVE"
            for object_id in release_gaps
        ):
            planned_resolution_releases += 1
        elif not release_gaps and complete_now:
            planned_resolution_releases += 1
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
        planned_resolution_releases=planned_resolution_releases,
        gap_objects=len(gap_objects),
        resolved_gap_objects=len(resolved_gap_objects),
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
        known_size_objects=sum(1 for obj in objects.values() if obj.size_bytes is not None),
        sized_objects=len(objects),
        _collection_complete=snapshot.collection_coverage()[0],
        _collection_categories=snapshot.collection_coverage()[1],
    )
