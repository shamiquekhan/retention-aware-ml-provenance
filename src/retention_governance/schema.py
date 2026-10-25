"""Provider-neutral evidence and inventory schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

RetentionStatus = Literal["available", "expiring", "expired", "unknown"]
ArchiveStatus = Literal["none", "verified", "unverified", "inaccessible"]
ExpirationSource = Literal["observed", "derived", "unknown"]
CollectionStatus = Literal["complete", "partial", "failed", "not_requested", "unknown"]
EdgeRelation = Literal[
    "generated_by",
    "references",
    "child_of",
    "evaluates",
    "required_for_audit",
]


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class ArchiveRecord:
    status: ArchiveStatus = "none"
    digest: str | None = None
    verified_at: datetime | None = None
    accessible: bool = False
    archive_uri: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"none", "verified", "unverified", "inaccessible"}:
            raise ValueError(f"invalid archive status: {self.status}")
        if self.verified_at is not None and (self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None):
            raise ValueError("archive verification time must include a timezone")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ArchiveRecord":
        data = data or {}
        return cls(
            status=data.get("status", "none"),
            digest=data.get("digest"),
            verified_at=parse_time(data.get("verified_at")),
            accessible=bool(data.get("accessible", False)),
            archive_uri=data.get("archive_uri"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "digest": self.digest,
            "verified_at": format_time(self.verified_at),
            "accessible": self.accessible,
            "archive_uri": self.archive_uri,
        }


@dataclass(frozen=True)
class EvidenceObject:
    object_id: str
    provider: str
    object_type: str
    created_at: datetime | None
    expires_at: datetime | None
    retention_status: RetentionStatus
    digest: str | None
    size_bytes: int | None
    source_uri: str | None
    policy_version: str
    protected: bool = False
    archive: ArchiveRecord = field(default_factory=ArchiveRecord)
    expiration_source: ExpirationSource = "observed"

    def __post_init__(self) -> None:
        if not self.object_id:
            raise ValueError("evidence object ID must not be empty")
        if self.retention_status not in {"available", "expiring", "expired", "unknown"}:
            raise ValueError(f"invalid retention status: {self.retention_status}")
        if self.expiration_source not in {"observed", "derived", "unknown"}:
            raise ValueError(f"invalid expiration source: {self.expiration_source}")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative: {self.object_id}")
        if self.digest is not None and ":" not in self.digest:
            raise ValueError(f"digest must include an algorithm prefix: {self.object_id}")
        for label, value in (("created_at", self.created_at), ("expires_at", self.expires_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must include a timezone: {self.object_id}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceObject":
        return cls(
            object_id=data["object_id"],
            provider=data["provider"],
            object_type=data["object_type"],
            created_at=parse_time(data.get("created_at")),
            expires_at=parse_time(data.get("expires_at")),
            retention_status=data.get("retention_status", "unknown"),
            digest=data.get("digest"),
            size_bytes=data.get("size_bytes"),
            source_uri=data.get("source_uri"),
            policy_version=data["policy_version"],
            protected=bool(data.get("protected", False)),
            archive=ArchiveRecord.from_dict(data.get("archive")),
            expiration_source=data.get("expiration_source", "observed"),
        )

    def archive_verified(self) -> bool:
        if self.archive.status != "verified" or not self.archive.accessible:
            return False
        if not self.digest or not self.archive.digest or not self.archive.archive_uri:
            return False
        if self.archive.verified_at is None:
            return False
        return self.archive.digest == self.digest

    def survives_until(self, horizon: datetime) -> bool:
        """Conservatively require an explicit expiration boundary."""
        if self.retention_status not in {"available", "expiring"}:
            return False
        if self.expiration_source != "observed":
            return False
        if self.expires_at is None:
            return False
        return self.expires_at >= horizon

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "provider": self.provider,
            "object_type": self.object_type,
            "created_at": format_time(self.created_at),
            "expires_at": format_time(self.expires_at),
            "retention_status": self.retention_status,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "source_uri": self.source_uri,
            "policy_version": self.policy_version,
            "protected": self.protected,
            "archive": self.archive.as_dict(),
            "expiration_source": self.expiration_source,
        }


@dataclass(frozen=True)
class EvidenceEdge:
    dependent_id: str
    prerequisite_id: str
    relation: EdgeRelation

    def __post_init__(self) -> None:
        if not self.dependent_id or not self.prerequisite_id:
            raise ValueError("evidence edge endpoints must not be empty")
        if self.relation not in {"generated_by", "references", "child_of", "evaluates", "required_for_audit"}:
            raise ValueError(f"invalid evidence edge relation: {self.relation}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceEdge":
        return cls(
            dependent_id=data["dependent_id"],
            prerequisite_id=data["prerequisite_id"],
            relation=data["relation"],
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "dependent_id": self.dependent_id,
            "prerequisite_id": self.prerequisite_id,
            "relation": self.relation,
        }


@dataclass(frozen=True)
class ReleaseRequirement:
    release_id: str
    audit_horizon: datetime
    required_object_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.release_id:
            raise ValueError("release ID must not be empty")
        if self.audit_horizon.tzinfo is None or self.audit_horizon.utcoffset() is None:
            raise ValueError("audit horizon must include a timezone")
        if len(set(self.required_object_ids)) != len(self.required_object_ids):
            raise ValueError(f"duplicate required object ID in release: {self.release_id}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseRequirement":
        audit_horizon = parse_time(data.get("audit_horizon"))
        if audit_horizon is None:
            raise ValueError("release requirement needs an explicit audit horizon")
        return cls(
            release_id=data["release_id"],
            audit_horizon=audit_horizon,
            required_object_ids=tuple(data["required_object_ids"]),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "audit_horizon": format_time(self.audit_horizon),
            "required_object_ids": list(self.required_object_ids),
        }


@dataclass(frozen=True)
class InventorySnapshot:
    snapshot_id: str
    captured_at: datetime
    now: datetime
    policy_version: str
    objects: tuple[EvidenceObject, ...]
    edges: tuple[EvidenceEdge, ...]
    releases: tuple[ReleaseRequirement, ...]
    api_requests: int = 0
    failed_requests: int = 0
    unknown_objects: int = 0
    collection_status: CollectionStatus = "complete"
    collection_states: tuple[tuple[str, CollectionStatus], ...] = ()

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot ID must not be empty")
        for label, value in (("captured_at", self.captured_at), ("now", self.now)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} must include a timezone")
        if self.api_requests < 0 or self.failed_requests < 0 or self.unknown_objects < 0:
            raise ValueError("inventory counters must be non-negative")
        if self.failed_requests > self.api_requests:
            raise ValueError("failed_requests cannot exceed api_requests")
        if self.collection_status not in {"complete", "partial", "failed", "not_requested", "unknown"}:
            raise ValueError(f"invalid collection status: {self.collection_status}")
        state_names: set[str] = set()
        for name, status in self.collection_states:
            if not name or name in state_names:
                raise ValueError(f"duplicate or empty collection state: {name}")
            if status not in {"complete", "partial", "failed", "not_requested", "unknown"}:
                raise ValueError(f"invalid collection state: {status}")
            state_names.add(name)
        self.object_map()
        seen_edges: set[tuple[str, str, str]] = set()
        for edge in self.edges:
            key = (edge.dependent_id, edge.prerequisite_id, edge.relation)
            if key in seen_edges:
                raise ValueError(f"duplicate evidence edge: {key}")
            seen_edges.add(key)
        release_ids = [release.release_id for release in self.releases]
        if len(set(release_ids)) != len(release_ids):
            raise ValueError("duplicate release requirement ID")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventorySnapshot":
        raw_states = data.get("collection_states", {})
        if isinstance(raw_states, dict):
            collection_states = tuple(sorted((str(name), status) for name, status in raw_states.items()))
        else:
            collection_states = tuple((str(name), status) for name, status in raw_states)
        return cls(
            snapshot_id=data["snapshot_id"],
            captured_at=parse_time(data["captured_at"]),
            now=parse_time(data["now"]),
            policy_version=data["policy_version"],
            objects=tuple(EvidenceObject.from_dict(item) for item in data["objects"]),
            edges=tuple(EvidenceEdge.from_dict(item) for item in data["edges"]),
            releases=tuple(ReleaseRequirement.from_dict(item) for item in data["releases"]),
            api_requests=int(data.get("api_requests", 0)),
            failed_requests=int(data.get("failed_requests", 0)),
            unknown_objects=int(data.get("unknown_objects", 0)),
            collection_status=data.get("collection_status", "complete"),
            collection_states=collection_states,
        )

    def object_map(self) -> dict[str, EvidenceObject]:
        result: dict[str, EvidenceObject] = {}
        for obj in self.objects:
            if obj.object_id in result:
                raise ValueError(f"duplicate evidence object ID: {obj.object_id}")
            result[obj.object_id] = obj
        return result

    def collection_state_map(self) -> dict[str, CollectionStatus]:
        return dict(self.collection_states)

    def collection_coverage(self) -> tuple[int, int]:
        """Return complete collection categories over expected categories."""
        if not self.collection_states:
            return (1, 1) if self.collection_status == "complete" else (0, 1)
        complete = sum(status == "complete" for _, status in self.collection_states)
        return complete, len(self.collection_states)

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "captured_at": format_time(self.captured_at),
            "now": format_time(self.now),
            "policy_version": self.policy_version,
            "objects": [item.as_dict() for item in self.objects],
            "edges": [item.as_dict() for item in self.edges],
            "releases": [item.as_dict() for item in self.releases],
            "api_requests": self.api_requests,
            "failed_requests": self.failed_requests,
            "unknown_objects": self.unknown_objects,
            "collection_status": self.collection_status,
            "collection_states": {name: status for name, status in self.collection_states},
        }
