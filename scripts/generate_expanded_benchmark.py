#!/usr/bin/env python3
"""Generate the frozen v0.2 sensitivity benchmark from deterministic seeds."""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retention_governance.generator import generate_inventory
from retention_governance.schema import ArchiveRecord


def build_cases(seed: int, count: int) -> list[dict[str, object]]:
    if count < 4:
        raise ValueError("count must be at least 4 to cover all benchmark variants")
    cases: list[dict[str, object]] = []
    variants = ("baseline", "partial_inventory", "missing_child", "unverified_archive")
    for index in range(count):
        snapshot = generate_inventory(seed, index=index)
        variant = variants[index % len(variants)]
        if variant == "partial_inventory":
            snapshot = replace(
                snapshot,
                collection_status="partial",
                collection_states=(("workflow_runs", "partial"), ("oci_manifests", "complete")),
            )
        elif variant == "missing_child":
            snapshot = replace(
                snapshot,
                objects=tuple(obj for obj in snapshot.objects if obj.object_type != "oci-manifest"),
                collection_status="partial",
                collection_states=(("workflow_runs", "complete"), ("oci_manifests", "partial")),
            )
        elif variant == "unverified_archive":
            snapshot = replace(
                snapshot,
                objects=tuple(
                    replace(
                        obj,
                        archive=ArchiveRecord(
                            status="unverified",
                            digest="sha256:wrong",
                            verified_at=None,
                            accessible=False,
                        ),
                    )
                    if obj.object_type == "oci-manifest" else obj
                    for obj in snapshot.objects
                ),
            )
        cases.append(
            {
                "case_id": f"expanded-{index:03d}-{variant}",
                "description": f"Seeded v0.2 generated inventory variant: {variant}.",
                "inventory": snapshot.as_dict(),
            }
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic expanded retention benchmark.")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--output", type=Path, default=ROOT / "scenarios" / "expanded.json")
    args = parser.parse_args()
    payload = {
        "benchmark_version": "0.2",
        "description": "Expanded deterministic sensitivity benchmark with collection and archive failures.",
        "seed": args.seed,
        "cases": build_cases(args.seed, args.count),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "case_count": len(payload["cases"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
