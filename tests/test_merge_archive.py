from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from retention_governance.archive import verify_archive, verify_archive_content
from retention_governance.graph import EvidenceGraph
from retention_governance.merge import CrossServiceReference, attach_references, merge_snapshots
from retention_governance.planner import plan_retention
from retention_governance.schema import EvidenceEdge, EvidenceObject, InventorySnapshot, ReleaseRequirement

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
HORIZON = NOW + timedelta(days=365)


def object_(object_id, provider, object_type, digest, expires_at=None, status='unknown'):
    return EvidenceObject(
        object_id=object_id,
        provider=provider,
        object_type=object_type,
        created_at=NOW,
        expires_at=expires_at,
        retention_status=status,
        digest=digest,
        size_bytes=10,
        source_uri=f'{provider}://{object_id}',
        policy_version='test-0.1',
    )


def snapshot(snapshot_id, objects, edges=()):
    return InventorySnapshot(
        snapshot_id=snapshot_id,
        captured_at=NOW,
        now=NOW,
        policy_version='test-0.1',
        objects=tuple(objects),
        edges=tuple(edges),
        releases=(),
    )


def test_cross_service_join_builds_transitive_release_closure():
    github = snapshot(
        'github',
        [object_('github:repo:release:1', 'github', 'release-record', 'sha256:release'),
         object_('github:repo:workflow:7', 'github_actions', 'workflow-run', 'sha256:workflow')],
        [EvidenceEdge('github:repo:release:1', 'github:repo:workflow:7', 'generated_by')],
    )
    ghcr = snapshot(
        'ghcr',
        [object_('ghcr:org/model:digest:sha256:index', 'ghcr', 'oci-index', 'sha256:index'),
         object_('ghcr:org/model:digest:sha256:child', 'ghcr', 'oci-manifest', 'sha256:child')],
        [EvidenceEdge('ghcr:org/model:digest:sha256:index', 'ghcr:org/model:digest:sha256:child', 'child_of')],
    )
    merged = merge_snapshots(
        [github, ghcr],
        snapshot_id='cross-service',
        releases=(ReleaseRequirement('release-1', HORIZON, ('github:repo:release:1',)),),
    )
    joined = attach_references(
        merged,
        [CrossServiceReference('github:repo:release:1', 'ghcr:org/model:digest:sha256:index', 'references')],
    )
    closure = EvidenceGraph(joined.snapshot).closures_for_releases()['release-1']
    assert closure.missing_ids == frozenset()
    assert closure.required_ids == frozenset({
        'github:repo:release:1',
        'github:repo:workflow:7',
        'ghcr:org/model:digest:sha256:index',
        'ghcr:org/model:digest:sha256:child',
    })
    assert joined.missing_references == ()


def test_missing_cross_service_target_is_not_invented():
    source = snapshot('source', [object_('release', 'github', 'release-record', 'sha256:release')])
    joined = attach_references(
        source,
        [CrossServiceReference('release', 'ghcr:missing:digest:sha256:nope')],
    )
    assert joined.missing_references == ('ghcr:missing:digest:sha256:nope',)
    joined = replace(joined.snapshot, releases=(ReleaseRequirement('r', HORIZON, ('release',)),))
    plan = plan_retention(joined)
    assert any(action.object_id == 'ghcr:missing:digest:sha256:nope' and action.action == 'HOLD_FOR_REVIEW' for action in plan.actions)


def test_conflicting_duplicate_objects_fail_merge():
    left = snapshot('left', [object_('same', 'github', 'artifact', 'sha256:left')])
    right = snapshot('right', [object_('same', 'ghcr', 'artifact', 'sha256:right')])
    with pytest.raises(ValueError, match='conflicting evidence object'):
        merge_snapshots([left, right], snapshot_id='conflict')


def test_verified_archive_changes_expiring_plan_to_preserve():
    expiring = object_(
        'workflow', 'github_actions', 'workflow-log', 'sha256:workflow',
        expires_at=NOW + timedelta(days=10), status='expiring'
    )
    base = snapshot('archive', [object_('release', 'github', 'release-record', 'sha256:release', expires_at=HORIZON + timedelta(days=1), status='available'), expiring], [EvidenceEdge('release', 'workflow', 'generated_by')])
    base = replace(base, releases=(ReleaseRequirement('r', HORIZON, ('release',)),))
    assert {action.object_id: action.action for action in plan_retention(base).actions}['workflow'] == 'ARCHIVE'
    updated, receipt = verify_archive(
        expiring,
        archive_digest='sha256:workflow',
        archive_uri='s3://audit/workflow.tar',
        verified_at=NOW,
    )
    assert receipt.verified is True
    assert updated.archive.archive_uri == 's3://audit/workflow.tar'
    archived = replace(base, objects=(base.objects[0], updated))
    assert {action.object_id: action.action for action in plan_retention(archived).actions}['workflow'] == 'PRESERVE_DEPENDENCY'


def test_archive_digest_mismatch_remains_unverified():
    obj = object_('artifact', 'github_actions', 'artifact', 'sha256:source')
    updated, receipt = verify_archive(
        obj,
        archive_digest='sha256:other',
        archive_uri='s3://audit/artifact',
        verified_at=NOW,
    )
    assert receipt.verified is False
    assert updated.archive.status == 'unverified'
    assert 'does not match' in receipt.reason


def test_archive_content_is_hashed_before_verification():
    content = b'archive payload'
    obj = object_('artifact', 'github_actions', 'artifact', f'sha256:{hashlib.sha256(content).hexdigest()}')
    updated, receipt = verify_archive_content(
        obj,
        archive_content=content,
        archive_uri='s3://audit/artifact',
        verified_at=NOW,
    )
    assert receipt.verified is True
    assert updated.archive.status == 'verified'


def test_archive_without_source_digest_cannot_be_verified():
    obj = object_('artifact', 'github_actions', 'artifact', None)
    updated, receipt = verify_archive(
        obj,
        archive_digest='sha256:anything',
        archive_uri='s3://audit/artifact',
        verified_at=NOW,
    )
    assert receipt.verified is False
    assert updated.archive.status == 'unverified'
