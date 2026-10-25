"""Deterministic synthetic inventory generator for sensitivity tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import random

from .schema import ArchiveRecord, EvidenceEdge, EvidenceObject, InventorySnapshot, ReleaseRequirement


def generate_inventory(seed: int, *, index: int = 0) -> InventorySnapshot:
    """Generate a deterministic provider-like inventory with varied topology."""
    case_seed = (seed * 1_000_003 + index * 97_409) & 0xFFFFFFFF
    rng = random.Random(case_seed)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    horizon = now + timedelta(days=365)
    release_id = f"generated-release-{seed}-{index}"
    workflow_id = f"generated-workflow-{seed}-{index}"
    index_id = f"generated-index-{seed}-{index}"
    child_id = f"generated-child-{seed}-{index}"
    workflow_days = rng.choice((0, 30, 120, 365, 500))
    workflow_expiry = now + timedelta(days=workflow_days)
    workflow_status = "expired" if workflow_days == 0 else ("expiring" if workflow_days < 365 else "available")
    child_days = rng.choice((-30, 180, 365, 500, None))
    child_expiry = now + timedelta(days=child_days) if child_days is not None else None
    child_status = (
        "unknown" if child_days is None else
        "expired" if child_days < 0 else
        "expiring" if child_days < 365 else "available"
    )
    child_archive = {
        "status": "verified" if rng.choice((False, True)) and child_days is not None and child_days < 365 else "none",
        "digest": "sha256:child" if child_days is not None and child_days < 365 else None,
        "verified_at": now.isoformat() if child_days is not None and child_days < 365 else None,
        "accessible": bool(child_days is not None and child_days < 365 and rng.choice((False, True))),
        "archive_uri": f"s3://synthetic/{child_id}.tar",
    }
    objects = [
        EvidenceObject(
            release_id, "github", "release-record", now, now + timedelta(days=500),
            "available", "sha256:release", 10, f"github://{release_id}", "generated-0.2", True,
        ),
        EvidenceObject(
            workflow_id, "github_actions", "workflow-run", now, workflow_expiry,
            workflow_status, "sha256:workflow", rng.choice((None, 100)),
            f"github_actions://{workflow_id}", "generated-0.2",
        ),
        EvidenceObject(
            index_id, "ghcr", "oci-index", now, now + timedelta(days=500),
            "available", "sha256:index", 50, f"ghcr://{index_id}", "generated-0.2",
        ),
        EvidenceObject(
            child_id, "ghcr", "oci-manifest", now, child_expiry,
            child_status, "sha256:child", rng.choice((None, 75)),
            f"ghcr://{child_id}", "generated-0.2",
            archive=ArchiveRecord.from_dict(child_archive),
        ),
    ]
    edges = [
        EvidenceEdge(release_id, workflow_id, "generated_by"),
        EvidenceEdge(release_id, index_id, "references"),
        EvidenceEdge(index_id, child_id, "child_of"),
    ]
    releases = [ReleaseRequirement(release_id, horizon, (release_id,))]
    topology = rng.choice(("chain", "branch", "shared_child", "nested_index", "multi_release"))
    if topology == "branch":
        config_id = f"generated-config-{seed}-{index}"
        objects.append(EvidenceObject(
            config_id, "github", "training-config", now, now + timedelta(days=500),
            "available", "sha256:config", 20, f"github://{config_id}", "generated-0.2",
        ))
        edges.append(EvidenceEdge(release_id, config_id, "references"))
    elif topology == "shared_child":
        second_index_id = f"generated-index-b-{seed}-{index}"
        objects.append(EvidenceObject(
            second_index_id, "ghcr", "oci-index", now, now + timedelta(days=500),
            "available", "sha256:index-b", 50, f"ghcr://{second_index_id}", "generated-0.2",
        ))
        edges.extend((
            EvidenceEdge(release_id, second_index_id, "references"),
            EvidenceEdge(second_index_id, child_id, "child_of"),
        ))
    elif topology == "nested_index":
        nested_id = f"generated-nested-child-{seed}-{index}"
        objects.append(EvidenceObject(
            nested_id, "ghcr", "oci-manifest", now, child_expiry,
            child_status, "sha256:nested", 40, f"ghcr://{nested_id}", "generated-0.2",
        ))
        objects = [replace(obj, object_type="oci-index") if obj.object_id == child_id else obj for obj in objects]
        edges.append(EvidenceEdge(child_id, nested_id, "child_of"))
    elif topology == "multi_release":
        second_release_id = f"generated-release-b-{seed}-{index}"
        objects.append(EvidenceObject(
            second_release_id, "github", "release-record", now, now + timedelta(days=500),
            "available", "sha256:release-b", 10, f"github://{second_release_id}", "generated-0.2",
        ))
        edges.append(EvidenceEdge(second_release_id, index_id, "references"))
        releases.append(ReleaseRequirement(second_release_id, horizon, (second_release_id,)))
    return InventorySnapshot(
        snapshot_id=f"generated-snapshot-{seed}-{index}",
        captured_at=now,
        now=now,
        policy_version="generated-0.2",
        objects=tuple(objects),
        edges=tuple(edges),
        releases=tuple(releases),
        api_requests=8,
        failed_requests=0,
        unknown_objects=sum(1 for obj in objects if obj.retention_status == "unknown"),
    )


def generate_inventories(seed: int, count: int) -> list[InventorySnapshot]:
    if count < 1:
        raise ValueError("count must be positive")
    return [generate_inventory(seed, index=index) for index in range(count)]
