# Retention-Aware ML Provenance

A separate systems-research workspace for studying whether dependency-aware retention governance can preserve the evidence required to reconstruct machine-learning releases across infrastructure retention boundaries.

## Research scope

The first milestone is synthetic and read-only. It does **not** connect to GitHub, GHCR, Langfuse, object storage, or any real account. The core comparison is:

- native/provider-like retention;
- independent per-service TTL decisions;
- a dependency-aware preservation planner;
- a conservative preserve-everything reference.

The planner produces a dry-run plan only. It never deletes, changes retention settings, uploads archives, or contacts external services.

## Research question

Can a dependency-aware planner detect retention gaps and protect transitive release evidence while avoiding unnecessary retention compared with independent TTL rules?

## First milestone

The current implementation contains:

- a provider-neutral evidence object and provenance-edge schema;
- a dependency graph with transitive required-evidence closure;
- a deterministic dry-run planner with `PRESERVE`, `PRESERVE_DEPENDENCY`, `ARCHIVE`, `CANDIDATE_FOR_DELETION` and `HOLD_FOR_REVIEW` decisions;
- a frozen synthetic benchmark with OCI parent/child relationships, expiring evidence, verified archives, unknown dependencies, protected objects and shared digests;
- explicit completeness, retention-gap, unsafe-deletion, preservation-overhead and operational-coverage metrics;
- workload-level aggregation across native, independent-TTL, conservative and dependency-aware strategies;
- a normalized benchmark-manifest hash and deterministic seeded scenario generator for sensitivity checks.

## Run it

```bash
python3 scripts/run_benchmark.py \
  --scenarios scenarios/pilot.json \
  --output reports/pilot_report.json
```

The output is machine-readable and includes the benchmark-manifest hash, per-case inventory/planner hashes, baseline comparisons, aggregated strategy metrics and explicit metric denominators.

## Checks

```bash
python3 -m pytest -q
python3 -m compileall -q src tests scripts
```

The project intentionally uses Python's standard library for the first milestone. A mocked, read-only GitHub Actions adapter is now included as the first provider slice; it does not run during the synthetic benchmark and has no destructive operations. GHCR manifest retrieval, checks/status normalization, Langfuse, notebooks, archive upload and deletion execution remain later phases and require separate authorization and dependency decisions.

## GitHub Actions adapter

The adapter is documented in `research/provider_gate.md` and can be run with:

```bash
python3 scripts/audit_github_actions.py \
  --owner OWNER \
  --repo REPO \
  --output reports/github_actions_inventory.json
```

It performs GET requests only. If retention settings or other evidence are not
available, it emits warnings and preserves unknown state rather than assuming
indefinite retention. Check runs and commit statuses can be enabled explicitly
with `--include-checks --include-statuses`.

For GHCR/OCI manifest dependencies:

```bash
python3 scripts/audit_ghcr.py \
  --owner OWNER \
  --package IMAGE_NAME \
  --reference TAG_OR_DIGEST \
  --output reports/ghcr_inventory.json
```

The GHCR adapter preserves parent-index/child-manifest edges and holds missing
child digests for review. It does not yet fetch image layers/config blobs or
infer registry retention.

## Safety and governance constraints

- Default mode is dry-run and read-only.
- Unknown or incomplete dependency metadata produces `HOLD_FOR_REVIEW`, never deletion eligibility.
- An unverified archive cannot substitute for a verified preservation copy.
- OCI child manifests referenced by a retained parent index are transitive dependencies.
- Raw provider responses and credentials are not committed.
- This tool is a technical policy auditor, not a legal-compliance verifier.
