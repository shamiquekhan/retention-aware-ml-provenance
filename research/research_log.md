# Research log

## 2026-10-25 — Synthetic benchmark and planner milestone

- Created a separate infrastructure-governance project; the safety-policy-retention repository remains separate and untouched.
- Implemented provider-neutral evidence objects, dependency edges, release audit horizons and transitive closure.
- Implemented a deterministic dry-run planner with preserve, archive, candidate-deletion and hold-for-review decisions.
- Added five synthetic cases covering multi-architecture OCI dependencies, expiring evidence, verified archives, missing dependencies and shared digests.
- Added workload-level aggregation for native, independent-TTL, conservative and dependency-aware strategies.
- Added a normalized benchmark manifest hash and deterministic seeded scenario generator.
- No provider API, archive upload or deletion execution has been implemented.

## Next gate

Before adding read-only GitHub Actions or GHCR adapters, expand the synthetic matrix enough to test provider response failures, pagination, rate limits, conflicting identifiers and archive verification outcomes.

## 2026-10-25 — GitHub Actions adapter milestone

- Added a read-only, pagination-aware GitHub Actions adapter for repository metadata, retention settings, workflow runs and artifacts.
- Added mocked tests for authentication headers, per-artifact expiration, derived workflow retention, pagination and failed settings requests.
- The adapter records request metadata and preserves unknown retention when settings or expiration data are unavailable.
- Checks, commit statuses, organization inheritance and archive export remain outside this first provider slice.

## 2026-10-25 — Checks/statuses and GHCR dependency milestone

- Added optional read-only normalization of GitHub check runs and commit statuses for observed head commits.
- Added a read-only GHCR/OCI manifest adapter that preserves parent-to-child digest edges and holds missing child manifests for review.
- Added CLI entry points for GitHub Actions and GHCR inventories; both require explicit caller authorization and never perform mutations.
- GHCR layers/config blobs and provider-specific registry retention metadata remain uncollected and are represented as a documented limitation.

## 2026-10-25 — Cross-service graph and archive verification milestone

- Added snapshot merging under one frozen clock with conflict detection for duplicate evidence IDs and release requirements.
- Added explicit cross-service reference joins that retain missing targets as graph dependencies.
- Added archive verification receipts with digest matching, accessibility and archive URI fields.
- Verified that a valid archive changes an expiring required object from `ARCHIVE` to `PRESERVE_DEPENDENCY`, while mismatches remain unverified.
- Added `scripts/merge_inventories.py` and cross-service documentation.

## 2026-10-25 — v0.2 correctness hardening milestone

- Separated current completeness, verified projected completeness and gap-resolution coverage. Required deletion candidates now fail projected completeness.
- Reworked baselines to simulate provider expiration through the shared workload horizon instead of deleting every unprotected object.
- Added timezone, enum, counter, duplicate-ID, duplicate-edge, digest and collection-state validation to the schema.
- Added explicit `complete`, `partial`, `failed` and `unknown` collection states; incomplete inventories hold deletion decisions for review.
- Added derived-versus-observed expiration provenance. Provider-derived GitHub expiration timestamps are not treated as verified historical retention.
- Added GHCR registry challenge/token negotiation, shared-digest edge preservation and unresolved descriptor dependencies.
- Added archive-content hashing and regression coverage for missing source digests.
- Added deterministic CI for tests, compilation, benchmark output and generated-report credential checks.
