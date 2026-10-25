# Provider gate: GitHub Actions and GHCR read-only inventory

**Status:** Implemented as network-capable adapters with mocked tests. No live
provider account has been accessed by the repository checks.

## GitHub Actions collection

`GitHubActionsClient` performs GET requests for:

- repository metadata;
- repository artifact/log retention settings;
- paginated workflow runs;
- paginated artifacts for each workflow run;
- optional paginated check runs for each observed commit;
- optional paginated commit statuses for each observed commit.

It normalizes workflow runs, source commit references, workflow artifacts,
check runs and commit statuses into the provider-neutral evidence graph. Artifact
expiration uses the provider's per-artifact `expires_at` and `expired` fields.
Workflow, check-run and status expiration is marked as `derived` when calculated
from the current retention setting; the planner does not treat that estimate as
observed historical retention. Artifact `expires_at` values remain observed
provider fields. Collection state is recorded per endpoint as `complete`,
`partial`, `failed` or `unknown`.

Optional collection is explicit:

```bash
python3 scripts/audit_github_actions.py \
  --owner OWNER \
  --repo REPO \
  --release-requirements release-requirements.json \
  --include-checks \
  --include-statuses \
  --output reports/github_actions_inventory.json
```

## GHCR/OCI collection

`GHCRClient` performs GET requests to the OCI manifest endpoint for a supplied
tag or digest. It records the parent index, resolves child manifest descriptors,
and optionally fetches each child manifest to verify that the referenced content
is present. Parent-to-child `child_of` edges are preserved even when a child
fetch fails, so the planner can emit `HOLD_FOR_REVIEW` instead of treating the
child as safely retained.

For private registries, a `401` `WWW-Authenticate` challenge is followed to the
registry token service. The configured GitHub credential is used only for that
scoped exchange; manifest requests use the returned short-lived bearer token.
The client never puts credentials or exchanged tokens in its request log.

```bash
python3 scripts/audit_ghcr.py \
  --owner OWNER \
  --package IMAGE_NAME \
  --reference TAG_OR_DIGEST \
  --release-requirements release-requirements.json \
  --output reports/ghcr_inventory.json
```

Every release requirement must include an explicit future or current
`audit_horizon`; provider snapshot time is never substituted silently.

GHCR retention metadata is not inferred from registry availability. OCI objects
are marked with unknown retention unless a later provider-specific retention
source is joined to the inventory. Image layers and config blobs are not yet
fetched; the current slice focuses on index/manifest dependency safety.

## External behavior and uncertainty

Both adapters are read-only. They send no POST, PUT, PATCH or DELETE requests.
Request status, rate-limit metadata and failures are retained without response
bodies or credentials. Missing permissions, unavailable retention settings,
failed child-manifest fetches and omitted optional collections become explicit
warnings or unknown objects.

## Official references

- https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2026-03-10
- https://docs.github.com/en/rest/actions/artifacts?apiVersion=2026-03-10
- https://docs.github.com/en/rest/actions/permissions?apiVersion=2026-03-10
- https://docs.github.com/en/rest/checks/runs?apiVersion=2026-03-10
- https://docs.github.com/en/rest/commits/statuses?apiVersion=2026-03-10
- https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- https://github.com/opencontainers/distribution-spec/blob/main/spec.md
