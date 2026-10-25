"""Simple retention policies used as synthetic comparison baselines."""

from __future__ import annotations

from .graph import EvidenceGraph
from .planner import DecisionPlan, PlanAction, inventory_hash
from .schema import InventorySnapshot


def baseline_plan(snapshot: InventorySnapshot, strategy: str) -> DecisionPlan:
    if strategy not in {"native", "independent_ttl", "conservative"}:
        raise ValueError(f"unknown baseline strategy: {strategy}")
    objects = snapshot.object_map()
    graph = EvidenceGraph(snapshot)
    closures = graph.closures_for_releases()
    explicit_required = {
        object_id
        for release in snapshot.releases
        for object_id in release.required_object_ids
    }
    actions: list[PlanAction] = []
    for object_id in sorted(objects):
        obj = objects[object_id]
        if strategy == "conservative":
            actions.append(
                PlanAction("PRESERVE", object_id, "conservative baseline retains every inventoried object")
            )
            continue
        required = object_id in (explicit_required if strategy == "independent_ttl" else set())
        if required and obj.retention_status in {"available", "expiring"}:
            actions.append(PlanAction("PRESERVE", object_id, "explicit release requirement under baseline", required=True))
        elif obj.protected:
            actions.append(PlanAction("PRESERVE", object_id, "explicit policy protection"))
        elif obj.retention_status == "unknown" or obj.expires_at is None:
            actions.append(PlanAction("HOLD_FOR_REVIEW", object_id, "baseline cannot verify deletion eligibility"))
        else:
            actions.append(PlanAction("CANDIDATE_FOR_DELETION", object_id, "not explicitly retained by baseline"))
    for missing in sorted(set().union(*(set(item.missing_ids) for item in closures.values()))):
        actions.append(PlanAction("HOLD_FOR_REVIEW", missing, "required dependency absent from inventory", required=True))
    return DecisionPlan(
        planner_version=f"baseline:{strategy}",
        policy_version=snapshot.policy_version,
        inventory_hash=inventory_hash(snapshot),
        generated_at=snapshot.captured_at,
        actions=tuple(actions),
        missing_dependencies=tuple(sorted(set().union(*(set(item.missing_ids) for item in closures.values())))),
    )
