"""Archive verification records for dry-run retention planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

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
