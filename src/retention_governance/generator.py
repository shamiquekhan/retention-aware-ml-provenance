"""Deterministic synthetic inventory generator for sensitivity tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random

from .schema import ArchiveRecord, EvidenceEdge, EvidenceObject, InventorySnapshot, ReleaseRequirement


def generate_inventory(seed: int, *, index: int = 0) -> InventorySnapshot:
    """Generate one small provider-like inventory from a fixed seed."""
    rng = random.Random(seed)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    horizon = now + timedelta(days=365)
    release_id = f"generated-release-{seed}-{index}"
    workflow_id = f"generated-workflow-{seed}-{index}"
    index_id = f"generated-index-{seed}-{index}"
    child_id = f"generated-child-{seed}-{index}"
    workflow_days = rng.choice((30, 120, 500))
    workflow_expiry = now + timedelta(days=workflow_days)
    workflow_status = "expiring" if workflow_days < 365 else "available"
    child_days = rng.choice((180, 500))
    child_expiry = now + timedelta(days=child_days)
    child_status = "expiring" if child_days < 365 else "available"
    child_archive = {
        "status": "verified" if rng.choice((False, True)) and child_days < 365 else "none",
        "digest": "sha256:child" if child_days < 365 else None,
        "verified_at": now.isoformat() if child_days < 365 else None,
        "accessible": bool(child_days < 365 and rng.choice((False, True))),
    }
    objects = (
        EvidenceObject(
            release_id, "github", "release-record", now, now + timedelta(days=500),
            "available", "sha256:release", 10, f"github://{release_id}", "generated-0.1", True
        ),
        EvidenceObject(
            workflow_id, "github_actions", "workflow-run", now, workflow_expiry,
            workflow_status, "sha256:workflow", 100, f"github_actions://{workflow_id}", "generated-0.1"
        ),
        EvidenceObject(
            index_id, "ghcr", "oci-index", now, now + timedelta(days=500),
            "available", "sha256:index", 50, f"ghcr://{index_id}", "generated-0.1"
        ),
        EvidenceObject(
            child_id, "ghcr", "oci-manifest", now, child_expiry,
            child_status, "sha256:child", 75, f"ghcr://{child_id}", "generated-0.1",
            archive=ArchiveRecord.from_dict(child_archive)
        ),
    )
    edges = (
        EvidenceEdge(release_id, workflow_id, "generated_by"),
        EvidenceEdge(release_id, index_id, "references"),
        EvidenceEdge(index_id, child_id, "child_of"),
    )
    return InventorySnapshot(
        snapshot_id=f"generated-snapshot-{seed}-{index}",
        captured_at=now,
        now=now,
        policy_version="generated-0.1",
        objects=objects,
        edges=edges,
        releases=(ReleaseRequirement(release_id, horizon, (release_id,)),),
        api_requests=8,
        failed_requests=0,
        unknown_objects=0,
    )


def generate_inventories(seed: int, count: int) -> list[InventorySnapshot]:
    if count < 1:
        raise ValueError("count must be positive")
    return [generate_inventory(seed, index=index) for index in range(count)]
