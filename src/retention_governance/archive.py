"""Archive verification records for dry-run retention planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib

from .schema import ArchiveRecord, EvidenceObject


@dataclass(frozen=True)
class ArchiveVerification:
    object_id: str
    verified: bool
    reason: str
    archive: ArchiveRecord


def verify_archive(
    obj: EvidenceObject,
    *,
    archive_digest: str | None,
    archive_uri: str | None,
    verified_at: datetime,
    accessible: bool = True,
) -> tuple[EvidenceObject, ArchiveVerification]:
    """Attach a verification receipt without touching the source or archive."""
    if not accessible:
        verified = False
        reason = "archive is not accessible for verification"
    elif not archive_uri:
        verified = False
        reason = "archive URI is unavailable"
    elif obj.digest is None:
        verified = False
        reason = "source content digest is unavailable"
    elif archive_digest != obj.digest:
        verified = False
        reason = "archive digest does not match source digest"
    else:
        verified = True
        reason = "archive digest matches source digest and archive is accessible"
    record = ArchiveRecord(
        status="verified" if verified else "unverified",
        digest=archive_digest,
        verified_at=verified_at,
        accessible=accessible,
        archive_uri=archive_uri,
    )
    updated = replace(obj, archive=record)
    return updated, ArchiveVerification(obj.object_id, verified, reason, record)


def verify_archive_content(
    obj: EvidenceObject,
    *,
    archive_content: bytes,
    archive_uri: str | None,
    verified_at: datetime,
    accessible: bool = True,
) -> tuple[EvidenceObject, ArchiveVerification]:
    """Hash archive content before creating a verification receipt."""
    if obj.digest is None:
        archive_digest = None
    else:
        algorithm, _, _ = obj.digest.partition(":")
        if algorithm != "sha256":
            archive_digest = f"{algorithm}:unsupported"
        else:
            archive_digest = f"sha256:{hashlib.sha256(archive_content).hexdigest()}"
    return verify_archive(
        obj,
        archive_digest=archive_digest,
        archive_uri=archive_uri,
        verified_at=verified_at,
        accessible=accessible,
    )


def verify_archive_contents(
    obj: EvidenceObject,
    *,
    archive_content: bytes,
    archive_uri: str | None,
    verified_at: datetime,
    accessible: bool = True,
) -> tuple[EvidenceObject, ArchiveVerification]:
    """Plural-name API for callers that verify a complete archive payload."""
    return verify_archive_content(
        obj,
        archive_content=archive_content,
        archive_uri=archive_uri,
        verified_at=verified_at,
        accessible=accessible,
    )
