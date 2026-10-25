"""Frozen synthetic benchmark runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .baselines import baseline_plan
from .metrics import evaluate_plan
from .planner import plan_retention
from .schema import InventorySnapshot


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    return list(data["cases"])



def benchmark_hash(path: Path) -> str:
    """Hash the normalized benchmark manifest, not filesystem metadata."""
    data = json.loads(path.read_text())
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _merge_rate(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    numerator = left["numerator"] + right["numerator"]
    denominator = left["denominator"] + right["denominator"]
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def aggregate_metrics(case_results: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    """Aggregate counts across cases without averaging already-normalized rates."""
    if not case_results:
        raise ValueError("cannot aggregate an empty benchmark")
    metric_rows = [result["strategies"][strategy]["metrics"] for result in case_results]
    rate_keys = {
        "current_evidence_chain_completeness",
        "planned_evidence_chain_completeness",
        "retention_gap_incidence",
        "unsafe_deletion_proposal_rate",
        "inventory_coverage",
    }
    aggregate: dict[str, Any] = {}
    for key in metric_rows[0]:
        if key in rate_keys:
            value = metric_rows[0][key]
            for row in metric_rows[1:]:
                value = _merge_rate(value, row[key])
            aggregate[key] = value
        elif key == "earliest_gap_lead_time_days":
            values = [row[key] for row in metric_rows if row[key] is not None]
            aggregate[key] = min(values) if values else None
        elif isinstance(metric_rows[0][key], int):
            aggregate[key] = sum(row[key] for row in metric_rows)
    return aggregate

def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    snapshot = InventorySnapshot.from_dict(case["inventory"])
    plans = {
        "native": baseline_plan(snapshot, "native"),
        "independent_ttl": baseline_plan(snapshot, "independent_ttl"),
        "conservative": baseline_plan(snapshot, "conservative"),
        "dependency_aware": plan_retention(snapshot),
    }
    expected_actions = case.get("expected", {}).get("dependency_aware_actions", {})
    actual_actions = {action.object_id: action.action for action in plans["dependency_aware"].actions}
    for object_id, expected_action in expected_actions.items():
        if actual_actions.get(object_id) != expected_action:
            raise ValueError(
                f"ground-truth mismatch for {case['case_id']}:{object_id}: "
                f"expected {expected_action}, got {actual_actions.get(object_id)}"
            )
    return {
        "case_id": case["case_id"],
        "description": case["description"],
        "strategies": {
            name: {"plan": plan.as_dict(), "metrics": evaluate_plan(snapshot, plan).as_dict()}
            for name, plan in plans.items()
        },
        "expected": case.get("expected", {}),
    }


def evaluate_benchmark(path: Path) -> dict[str, Any]:
    cases = load_cases(path)
    results = [evaluate_case(case) for case in cases]
    strategies = ("native", "independent_ttl", "conservative", "dependency_aware")
    return {
        "benchmark": str(path),
        "benchmark_hash": benchmark_hash(path),
        "case_count": len(cases),
        "strategies": {strategy: aggregate_metrics(results, strategy) for strategy in strategies},
        "cases": results,
    }
