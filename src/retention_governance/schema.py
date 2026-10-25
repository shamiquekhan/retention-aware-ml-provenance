"""Provider-neutral evidence and inventory schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

RetentionStatus = Literal["available", "expiring", "expired", "unknown"]
ArchiveStatus = Literal["none", "verified", "unverified", "inaccessible"]
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
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class ArchiveRecord:
    status: ArchiveStatus = "none"
    digest: str | None = None
    verified_at: datetime | None = None
    accessible: bool = False
    archive_uri: str | None = None

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
        )

    def archive_verified(self) -> bool:
        if self.archive.status != "verified" or not self.archive.accessible:
            return False
        if self.digest is None:
            return True
        return self.archive.digest == self.digest

    def survives_until(self, horizon: datetime) -> bool:
        """Conservatively require an explicit expiration boundary."""
        if self.retention_status not in {"available", "expiring"}:
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
        }


@dataclass(frozen=True)
class EvidenceEdge:
    dependent_id: str
    prerequisite_id: str
    relation: EdgeRelation

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReleaseRequirement":
        return cls(
            release_id=data["release_id"],
            audit_horizon=parse_time(data["audit_horizon"]),
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventorySnapshot":
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
        )

    def object_map(self) -> dict[str, EvidenceObject]:
        result: dict[str, EvidenceObject] = {}
        for obj in self.objects:
            if obj.object_id in result:
                raise ValueError(f"duplicate evidence object ID: {obj.object_id}")
            result[obj.object_id] = obj
        return result

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
        }
