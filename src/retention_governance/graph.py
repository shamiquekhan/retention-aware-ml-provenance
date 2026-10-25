"""Dependency graph and required-evidence closure."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .schema import EvidenceEdge, InventorySnapshot


@dataclass(frozen=True)
class ClosureResult:
    required_ids: frozenset[str]
    missing_ids: frozenset[str]
    edges: tuple[EvidenceEdge, ...]


class EvidenceGraph:
    """Graph where every edge points from a dependent to a prerequisite."""

    def __init__(self, snapshot: InventorySnapshot) -> None:
        self.snapshot = snapshot
        self.objects = snapshot.object_map()
        self._dependencies: dict[str, list[EvidenceEdge]] = defaultdict(list)
        seen_edges: set[tuple[str, str, str]] = set()
        for edge in snapshot.edges:
            key = (edge.dependent_id, edge.prerequisite_id, edge.relation)
            if key in seen_edges:
                raise ValueError(f"duplicate evidence edge: {key}")
            seen_edges.add(key)
            self._dependencies[edge.dependent_id].append(edge)

    def required_closure(self, roots: set[str]) -> ClosureResult:
        required: set[str] = set()
        missing: set[str] = set()
        traversed: list[EvidenceEdge] = []
        queue = deque(roots)
        while queue:
            object_id = queue.popleft()
            if object_id in required:
                continue
            required.add(object_id)
            if object_id not in self.objects:
                missing.add(object_id)
                continue
            for edge in self._dependencies.get(object_id, []):
                traversed.append(edge)
                queue.append(edge.prerequisite_id)
        return ClosureResult(frozenset(required), frozenset(missing), tuple(traversed))

    def closures_for_releases(self) -> dict[str, ClosureResult]:
        return {
            release.release_id: self.required_closure(set(release.required_object_ids))
            for release in self.snapshot.releases
        }
