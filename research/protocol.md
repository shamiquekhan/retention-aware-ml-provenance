# Research protocol: Evidence-Aware Retention Governance

**Status:** Synthetic pilot, version 0.2 correctness milestone
**Date:** 2026-10-25

## Research question

Can a dependency-aware planner detect retention gaps and preserve the minimum
transitive evidence required to reconstruct a machine-learning release, while
avoiding unsafe deletion proposals and unnecessary retention under provider-like
expiration and inventory failures?

## Scope boundary

This repository is separate from the safety-policy-retention project. It studies
infrastructure evidence retention, not learned policy behavior after runtime
guard removal. The first milestone is provider-neutral and synthetic. Real
GitHub, GHCR, Langfuse and archive integrations are deferred until the synthetic
planner passes the invariant suite and a read-only access design is approved.

## Formal objects

The inventory is a directed dependency graph `G=(V,E)`. Every edge points from a
dependent object to a prerequisite. For example, an OCI index points to each
child manifest it references, and a model release points to its workflow run,
training configuration and container index.

A release has an audit horizon and a set of root evidence objects. The required
closure is the transitive set reached by following prerequisite edges. An object
is available through a horizon only when its source expiration is explicitly
known and no earlier than that horizon, or when an accessible archive has been
verified against the object's digest. A missing expiration is not treated as
infinite retention.

## Dry-run decisions

The planner emits decisions, never destructive actions:

- `PRESERVE`: required evidence remains available or has a verified archive.
- `PRESERVE_DEPENDENCY`: transitive prerequisite of required evidence.
- `ARCHIVE`: required evidence expires before the horizon and needs a verified
  preservation copy.
- `CANDIDATE_FOR_DELETION`: not required, not protected and metadata is
  sufficient for a dry-run candidate.
- `HOLD_FOR_REVIEW`: missing dependency, unknown retention, expired evidence
  without a verified archive, or unverified archive.

Unknown state is never interpreted as safe to delete.

## Evaluation metrics

All metrics expose numerator and denominator. The pilot reports:

1. current evidence-chain completeness;
2. verified projected evidence-chain completeness after modeled actions;
3. planned gap-resolution coverage, distinct from verified completeness;
4. retention-gap incidence and earliest gap lead time;
5. unsafe deletion proposal rate;
6. retained bytes and byte-days above the minimum required closure;
7. collection coverage, request success, unknown-object and known-size rates.

A proposed `ARCHIVE` action counts toward gap-resolution coverage but does not
count as verified projected completeness until the archive content has been
hashed and verified. A required `CANDIDATE_FOR_DELETION`, missing dependency or
`HOLD_FOR_REVIEW` always fails projected completeness.

The benchmark ground truth is synthetic and therefore permits exact invariant
checks. Real inventories will be treated as partial observations, not as proof
that unavailable evidence never existed.

## Baselines

- Native/provider-like retention with no cross-service dependency reasoning,
  simulated through the workload horizon from each object's provider expiration.
- Independent TTL decisions over each object's own expiration, without
  transitive dependency reasoning.
- Conservative retention of every inventoried object.
- Dependency-aware dry-run planner.

The first result is a planning comparison, not evidence that the planner can
safely delete infrastructure. Destructive execution is out of scope.
