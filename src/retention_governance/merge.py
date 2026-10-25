"""Merge provider inventories into one cross-service provenance graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from typing import Iterable

from .schema import CollectionStatus, EvidenceEdge, EvidenceObject, InventorySnapshot, ReleaseRequirement


@dataclass(frozen=True)
class CrossServiceReference:
    dependent_id: str
    prerequisite_id: str
    relation: str = "references"


@dataclass(frozen=True)
class JoinResult:
    snapshot: InventorySnapshot
    missing_references: tuple[str, ...]


def merge_snapshots(
    snapshots: Iterable[InventorySnapshot],
    *,
    snapshot_id: str,
    releases: Iterable[ReleaseRequirement] = (),
    now: datetime | None = None,
) -> InventorySnapshot:
    """Union provider snapshots while rejecting conflicting evidence records."""
    snapshots = tuple(snapshots)
    if not snapshots:
        raise ValueError("at least one snapshot is required")
    clock = now or snapshots[0].now
    objects: dict[str, EvidenceObject] = {}
    edges: dict[tuple[str, str, str], EvidenceEdge] = {}
    release_map: dict[str, ReleaseRequirement] = {}
    policy_versions: set[str] = set()
    captured_at = snapshots[0].captured_at
    api_requests = failed_requests = 0
    collection_states: dict[str, CollectionStatus] = {}
    for snapshot in snapshots:
        if snapshot.now != clock:
            raise ValueError("cross-service snapshots must share one frozen clock")
        captured_at = max(captured_at, snapshot.captured_at)
        policy_versions.add(snapshot.policy_version)
        api_requests += snapshot.api_requests
        failed_requests += snapshot.failed_requests
        for name, status in snapshot.collection_states:
            collection_states[f"{snapshot.snapshot_id}:{name}"] = status
        if not snapshot.collection_states and snapshot.collection_status != "complete":
            collection_states[f"{snapshot.snapshot_id}:__snapshot__"] = snapshot.collection_status
        for obj in snapshot.objects:
            existing = objects.get(obj.object_id)
            if existing is not None and existing != obj:
                raise ValueError(f"conflicting evidence object: {obj.object_id}")
            objects[obj.object_id] = obj
        for edge in snapshot.edges:
            key = (edge.dependent_id, edge.prerequisite_id, edge.relation)
            edges[key] = edge
        for release in snapshot.releases:
            existing_release = release_map.get(release.release_id)
            if existing_release is not None and existing_release != release:
                raise ValueError(f"conflicting release requirement: {release.release_id}")
            release_map[release.release_id] = release
    for release in releases:
        existing_release = release_map.get(release.release_id)
        if existing_release is not None and existing_release != release:
            raise ValueError(f"conflicting release requirement: {release.release_id}")
        release_map[release.release_id] = release
    policy_payload = json.dumps(sorted(policy_versions), separators=(",", ":"))
    policy_version = f"cross-service:{hashlib.sha256(policy_payload.encode()).hexdigest()[:16]}"
    if any(status == "failed" for status in collection_states.values()):
        collection_status: CollectionStatus = "failed"
    elif any(status in {"partial", "unknown"} for status in collection_states.values()):
        collection_status = "partial"
    else:
        collection_status = "complete"
    return InventorySnapshot(
        snapshot_id=snapshot_id,
        captured_at=captured_at,
        now=clock,
        policy_version=policy_version,
        objects=tuple(objects[key] for key in sorted(objects)),
        edges=tuple(edges[key] for key in sorted(edges)),
        releases=tuple(release_map[key] for key in sorted(release_map)),
        api_requests=api_requests,
        failed_requests=failed_requests,
        unknown_objects=sum(1 for obj in objects.values() if obj.retention_status == "unknown"),
        collection_status=collection_status,
        collection_states=tuple(sorted(collection_states.items())),
    )


def attach_references(
    snapshot: InventorySnapshot,
    references: Iterable[CrossServiceReference],
) -> JoinResult:
    """Add verified or missing cross-service edges without inventing objects."""
    objects = snapshot.object_map()
    edges = {
        (edge.dependent_id, edge.prerequisite_id, edge.relation): edge
        for edge in snapshot.edges
    }
    missing: set[str] = set()
    for reference in references:
        if reference.dependent_id not in objects:
            raise ValueError(f"cross-service dependent is absent: {reference.dependent_id}")
        edge = EvidenceEdge(
            reference.dependent_id,
            reference.prerequisite_id,
            reference.relation,
        )
        edges[(edge.dependent_id, edge.prerequisite_id, edge.relation)] = edge
        if reference.prerequisite_id not in objects:
            missing.add(reference.prerequisite_id)
    updated = replace(
        snapshot,
        edges=tuple(edges[key] for key in sorted(edges)),
    )
    return JoinResult(updated, tuple(sorted(missing)))
