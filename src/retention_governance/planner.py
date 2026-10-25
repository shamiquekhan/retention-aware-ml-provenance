"""Deterministic dry-run preservation planner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Literal

from .graph import EvidenceGraph
from .schema import EvidenceObject, InventorySnapshot

PlanActionType = Literal[
    "PRESERVE",
    "PRESERVE_DEPENDENCY",
    "ARCHIVE",
    "CANDIDATE_FOR_DELETION",
    "HOLD_FOR_REVIEW",
]


@dataclass(frozen=True)
class PlanAction:
    action: PlanActionType
    object_id: str
    reason: str
    release_ids: tuple[str, ...] = ()
    required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "object_id": self.object_id,
            "reason": self.reason,
            "release_ids": list(self.release_ids),
            "required": self.required,
        }


@dataclass(frozen=True)
class DecisionPlan:
    planner_version: str
    policy_version: str
    inventory_hash: str
    generated_at: datetime
    actions: tuple[PlanAction, ...]
    missing_dependencies: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "planner_version": self.planner_version,
            "policy_version": self.policy_version,
            "inventory_hash": self.inventory_hash,
            "generated_at": self.generated_at.isoformat(),
            "actions": [action.as_dict() for action in self.actions],
            "missing_dependencies": list(self.missing_dependencies),
        }


def inventory_hash(snapshot: InventorySnapshot) -> str:
    payload = json.dumps(snapshot.as_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _required_context(snapshot: InventorySnapshot) -> tuple[set[str], set[str], dict[str, set[str]], set[str]]:
    graph = EvidenceGraph(snapshot)
    closures = graph.closures_for_releases()
    required: set[str] = set()
    root_objects = {
        object_id
        for release in snapshot.releases
        for object_id in release.required_object_ids
    }
    release_ids_by_object: dict[str, set[str]] = {}
    missing: set[str] = set()
    for release_id, closure in closures.items():
        required.update(closure.required_ids)
        missing.update(closure.missing_ids)
        for object_id in closure.required_ids:
            release_ids_by_object.setdefault(object_id, set()).add(release_id)
    return required, root_objects, release_ids_by_object, missing


def _action_for_required(
    obj: EvidenceObject,
    *,
    horizon: datetime,
    release_ids: set[str],
    dependency: bool,
) -> PlanAction:
    common = {
        "object_id": obj.object_id,
        "release_ids": tuple(sorted(release_ids)),
        "required": True,
    }
    if obj.archive_verified():
        return PlanAction(
            action="PRESERVE_DEPENDENCY" if dependency else "PRESERVE",
            reason="verified archive satisfies the required audit horizon",
            **common,
        )
    if obj.survives_until(horizon):
        return PlanAction(
            action="PRESERVE_DEPENDENCY" if dependency else "PRESERVE",
            reason="source retention is verified through the required audit horizon",
            **common,
        )
    if obj.retention_status == "expired":
        return PlanAction(
            action="HOLD_FOR_REVIEW",
            reason="required evidence is already expired and has no verified archive",
            **common,
        )
    if obj.expires_at is not None and obj.expires_at < horizon:
        if obj.archive.status in {"unverified", "inaccessible"}:
            return PlanAction(
                action="HOLD_FOR_REVIEW",
                reason="required evidence needs preservation but its archive is not verified",
                **common,
            )
        return PlanAction(
            action="ARCHIVE",
            reason="source retention expires before the required audit horizon",
            **common,
        )
    return PlanAction(
        action="HOLD_FOR_REVIEW",
        reason="retention horizon cannot be verified from the inventory",
        **common,
    )


def plan_retention(snapshot: InventorySnapshot, *, planner_version: str = "0.1.0") -> DecisionPlan:
    """Create a no-delete dry-run plan from one frozen inventory snapshot."""

    objects = snapshot.object_map()
    required, root_objects, release_ids_by_object, missing = _required_context(snapshot)
    release_horizons = {release.release_id: release.audit_horizon for release in snapshot.releases}
    actions: list[PlanAction] = []
    inventory_incomplete = snapshot.collection_status != "complete" or any(
        status not in {"complete", "not_requested"} for _, status in snapshot.collection_states
    )

    for object_id in sorted(required):
        obj = objects.get(object_id)
        release_ids = release_ids_by_object.get(object_id, set())
        if obj is None:
            continue
        horizons = [release_horizons[release_id] for release_id in release_ids]
        horizon = max(horizons)
        dependency = object_id not in root_objects
        if inventory_incomplete:
            actions.append(
                PlanAction(
                    action="HOLD_FOR_REVIEW",
                    object_id=object_id,
                    reason="required evidence comes from an incomplete provider inventory",
                    release_ids=tuple(sorted(release_ids)),
                    required=True,
                )
            )
            continue
        actions.append(
            _action_for_required(
                obj,
                horizon=horizon,
                release_ids=release_ids,
                dependency=dependency,
            )
        )

    for object_id in sorted(set(objects) - required):
        obj = objects[object_id]
        if inventory_incomplete:
            actions.append(
                PlanAction(
                    action="HOLD_FOR_REVIEW",
                    object_id=object_id,
                    reason="deletion eligibility is blocked by an incomplete provider inventory",
                )
            )
        elif obj.protected:
            actions.append(
                PlanAction(
                    action="PRESERVE",
                    object_id=object_id,
                    reason="object is explicitly protected by policy",
                )
            )
        elif obj.retention_status == "unknown" or obj.expires_at is None:
            actions.append(
                PlanAction(
                    action="HOLD_FOR_REVIEW",
                    object_id=object_id,
                    reason="deletion eligibility is unknown from incomplete retention metadata",
                )
            )
        else:
            actions.append(
                PlanAction(
                    action="CANDIDATE_FOR_DELETION",
                    object_id=object_id,
                    reason="not required by any retained release dependency closure",
                )
            )

    for missing_id in sorted(missing):
        actions.append(
            PlanAction(
                action="HOLD_FOR_REVIEW",
                object_id=missing_id,
                reason="required dependency is absent from the inventory",
                required=True,
            )
        )

    return DecisionPlan(
        planner_version=planner_version,
        policy_version=snapshot.policy_version,
        inventory_hash=inventory_hash(snapshot),
        generated_at=snapshot.captured_at,
        actions=tuple(actions),
        missing_dependencies=tuple(sorted(missing)),
    )
