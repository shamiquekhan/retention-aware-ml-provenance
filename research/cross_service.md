# Cross-service provenance and archive gate

The provider adapters now produce separate snapshots. This layer merges them
under one frozen clock, rejects conflicting object IDs, attaches explicit
cross-service references, and preserves missing references as graph edges so the
planner can hold them for review.

## Example join

A caller can join a GitHub release or workflow object to a GHCR image index with
an explicit reference:

```json
[
  {
    "dependent_id": "github:org/repo:release:123",
    "prerequisite_id": "ghcr:org/model:digest:sha256:index",
    "relation": "references"
  }
]
```

The merge layer does not guess this relationship from tags, names or timestamps.
If the target digest is absent, it records the missing target and the planner
emits `HOLD_FOR_REVIEW`.

## Archive verification

`verify_archive` creates an immutable verification receipt from:

- the source content digest;
- the observed archive digest;
- an archive URI;
- accessibility at verification time;
- the verification timestamp.

Only a digest match on an accessible archive produces `status="verified"`.
Digest mismatch, inaccessible archives and source objects without a digest remain
unverified. The planner can then distinguish `PRESERVE` through a verified copy
from `ARCHIVE` or `HOLD_FOR_REVIEW`.

## Merge command

```bash
python3 scripts/merge_inventories.py \\
  --input reports/github_actions_inventory.json \\
  --input reports/ghcr_inventory.json \\
  --references cross-service-references.json \\
  --releases release-requirements.json \\
  --output reports/cross_service_inventory.json
```

This command is read-only and only writes a normalized local report.
