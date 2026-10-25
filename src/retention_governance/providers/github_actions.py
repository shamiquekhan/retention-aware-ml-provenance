"""Read-only GitHub Actions inventory adapter.

The adapter only performs GET requests. It normalizes repository metadata,
workflow runs, artifacts and optionally check runs and commit statuses into the
provider-neutral evidence schema. Missing permissions, pagination failures and
rate-limit responses remain visible in ``request_log`` and make retention state
unknown rather than being treated as safe defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..schema import CollectionStatus, EvidenceEdge, EvidenceObject, InventorySnapshot, ReleaseRequirement


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        ...


class UrllibTransport:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return HttpResponse(
                    status=response.status,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers={key.lower(): value for key, value in error.headers.items()},
                body=error.read(),
            )
        except URLError as error:
            raise ConnectionError(str(error.reason)) from error


@dataclass(frozen=True)
class GitHubActionsCollection:
    snapshot: InventorySnapshot
    repository: dict[str, Any]
    retention_settings: dict[str, Any] | None
    request_log: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...] = ()


class GitHubActionsClient:
    """Read-only client for repository-level Actions inventory endpoints."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.transport = transport or UrllibTransport()
        self._auth_header = f"Bearer {token}" if token else None
        self.request_log: list[dict[str, Any]] = []

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": "retention-aware-ml-provenance/0.2",
        }
        if self._auth_header:
            headers["Authorization"] = self._auth_header
        return headers

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any | None:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        try:
            response = self.transport.get(url, self._headers())
        except Exception as error:  # noqa: BLE001 - inventory failures are data
            self.request_log.append({"url": url, "status": None, "error": type(error).__name__})
            return None
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        entry = {"url": url, "status": response.status}
        if remaining is not None:
            entry["rate_limit_remaining"] = remaining
        if reset is not None:
            entry["rate_limit_reset"] = reset
        self.request_log.append(entry)
        if not 200 <= response.status < 300:
            entry["error"] = "http_error"
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            entry["error"] = "invalid_json"
            return None

    def _list_pages(self, path: str, key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._get_json(path, params={"per_page": 100, "page": page})
            if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
                break
            page_rows = [row for row in payload[key] if isinstance(row, dict)]
            rows.extend(page_rows)
            if len(page_rows) < 100:
                break
            page += 1
        return rows

    def _list_array_pages(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._get_json(path, params={"per_page": 100, "page": page})
            if not isinstance(payload, list):
                break
            page_rows = [row for row in payload if isinstance(row, dict)]
            rows.extend(page_rows)
            if len(page_rows) < 100:
                break
            page += 1
        return rows

    @staticmethod
    def _time(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _status(expires_at: datetime | None, expired: bool, now: datetime, warning_days: int) -> str:
        if expired or (expires_at is not None and expires_at <= now):
            return "expired"
        if expires_at is None:
            return "unknown"
        if expires_at <= now + timedelta(days=warning_days):
            return "expiring"
        return "available"

    @staticmethod
    def _object_id(owner: str, repo: str, kind: str, identifier: Any) -> str:
        return f"github:{owner}/{repo}:{kind}:{identifier}"

    def collect(
        self,
        owner: str,
        repo: str,
        *,
        now: datetime | None = None,
        warning_days: int = 30,
        release_roots: dict[str, tuple[str, ...]] | None = None,
        audit_horizon: datetime | None = None,
        release_requirements: tuple[ReleaseRequirement, ...] = (),
        include_checks: bool = False,
        include_statuses: bool = False,
    ) -> GitHubActionsCollection:
        """Collect an inventory without changing any provider state."""
        if warning_days < 0:
            raise ValueError("warning_days must be non-negative")
        now = now or datetime.now(timezone.utc)
        if release_roots and audit_horizon is None:
            raise ValueError("audit_horizon is required when release_roots are supplied")
        repository = self._get_json(f"/repos/{owner}/{repo}") or {}
        retention = self._get_json(
            f"/repos/{owner}/{repo}/actions/permissions/artifact-and-log-retention"
        )
        retention_days = retention.get("days") if isinstance(retention, dict) else None
        warnings: list[str] = []
        if not isinstance(retention, dict) or not isinstance(retention_days, int):
            warnings.append("retention_settings_unavailable")
        warnings.append("historical_expiration_unavailable_for_runs_checks_statuses")
        if not include_checks:
            warnings.append("check_runs_not_collected")
        if not include_statuses:
            warnings.append("commit_statuses_not_collected")
        runs = self._list_pages(f"/repos/{owner}/{repo}/actions/runs", "workflow_runs")
        objects: dict[str, EvidenceObject] = {}
        edges: list[EvidenceEdge] = []
        policy_version = f"github-actions:{self.api_version}:0.2"
        head_shas: set[str] = set()

        def ensure_commit(head_sha: str, created_at: datetime | None) -> str:
            commit_id = self._object_id(owner, repo, "commit", head_sha)
            if commit_id not in objects:
                objects[commit_id] = EvidenceObject(
                    object_id=commit_id,
                    provider="github",
                    object_type="source-commit",
                    created_at=created_at,
                    expires_at=None,
                    retention_status="unknown",
                    digest=f"sha1:{head_sha}",
                    size_bytes=None,
                    source_uri=f"https://github.com/{owner}/{repo}/commit/{head_sha}",
                    policy_version=policy_version,
                    expiration_source="unknown",
                )
            return commit_id

        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                continue
            run_object_id = self._object_id(owner, repo, "workflow-run", run_id)
            created_at = self._time(run.get("created_at"))
            objects[run_object_id] = EvidenceObject(
                object_id=run_object_id,
                provider="github_actions",
                object_type="workflow-run",
                created_at=created_at,
                expires_at=None,
                retention_status="available",
                digest=None,
                size_bytes=None,
                source_uri=run.get("html_url") or run.get("url"),
                policy_version=policy_version,
                expiration_source="unknown",
            )
            head_sha = run.get("head_sha")
            if head_sha:
                head_shas.add(head_sha)
                edges.append(EvidenceEdge(run_object_id, ensure_commit(head_sha, created_at), "references"))
            artifacts = self._list_pages(
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts", "artifacts"
            )
            for artifact in artifacts:
                artifact_id = artifact.get("id")
                if artifact_id is None:
                    continue
                artifact_object_id = self._object_id(owner, repo, "artifact", artifact_id)
                artifact_created = self._time(artifact.get("created_at"))
                artifact_expiry = self._time(artifact.get("expires_at"))
                objects[artifact_object_id] = EvidenceObject(
                    object_id=artifact_object_id,
                    provider="github_actions",
                    object_type="workflow-artifact",
                    created_at=artifact_created,
                    expires_at=artifact_expiry,
                    retention_status=self._status(
                        artifact_expiry,
                        bool(artifact.get("expired", False)),
                        now,
                        warning_days,
                    ),
                    digest=artifact.get("digest"),
                    size_bytes=artifact.get("size_in_bytes"),
                    source_uri=artifact.get("url") or artifact.get("archive_download_url"),
                    policy_version=policy_version,
                )
                edges.append(EvidenceEdge(artifact_object_id, run_object_id, "generated_by"))

        for head_sha in sorted(head_shas):
            commit_id = ensure_commit(head_sha, None)
            if include_checks:
                check_runs = self._list_pages(
                    f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs", "check_runs"
                )
                for check in check_runs:
                    check_id = check.get("id")
                    if check_id is None:
                        continue
                    created_at = self._time(check.get("started_at") or check.get("created_at"))
                    object_id = self._object_id(owner, repo, "check-run", check_id)
                    objects[object_id] = EvidenceObject(
                        object_id=object_id,
                        provider="github_actions",
                        object_type="check-run",
                        created_at=created_at,
                        expires_at=None,
                        retention_status="available",
                        digest=None,
                        size_bytes=None,
                        source_uri=check.get("html_url") or check.get("url"),
                        policy_version=policy_version,
                        expiration_source="unknown",
                    )
                    edges.append(EvidenceEdge(object_id, commit_id, "references"))
            if include_statuses:
                statuses = self._list_array_pages(
                    f"/repos/{owner}/{repo}/commits/{head_sha}/status"
                )
                for status in statuses:
                    status_id = status.get("id")
                    if status_id is None:
                        continue
                    created_at = self._time(status.get("created_at"))
                    object_id = self._object_id(owner, repo, "commit-status", status_id)
                    objects[object_id] = EvidenceObject(
                        object_id=object_id,
                        provider="github",
                        object_type="commit-status",
                        created_at=created_at,
                        expires_at=None,
                        retention_status="available",
                        digest=None,
                        size_bytes=None,
                        source_uri=status.get("target_url"),
                        policy_version=policy_version,
                        expiration_source="unknown",
                    )
                    edges.append(EvidenceEdge(object_id, commit_id, "references"))

        if include_checks and any(
            "/check-runs?" in str(entry.get("url")) and entry.get("status", 0) != 200
            for entry in self.request_log
        ):
            warnings.append("check_runs_incomplete")
        if include_statuses and any(
            "/status?" in str(entry.get("url")) and entry.get("status", 0) != 200
            for entry in self.request_log
        ):
            warnings.append("commit_statuses_incomplete")

        releases = tuple(release_requirements)
        if release_roots:
            releases += tuple(
                ReleaseRequirement(release_id, audit_horizon, tuple(root_ids))
                for release_id, root_ids in release_roots.items()
            )

        def endpoint_state(path: str, *, prefix: bool = False) -> CollectionStatus:
            entries = []
            for entry in self.request_log:
                url = str(entry.get("url", ""))
                base = url.split("?", 1)[0]
                if (base.endswith(path) if not prefix else path in base):
                    entries.append(entry)
            if not entries:
                return "unknown"
            statuses = [entry.get("status") for entry in entries]
            if all(isinstance(status, int) and 200 <= status < 300 for status in statuses):
                return "complete"
            if any(isinstance(status, int) and 200 <= status < 300 for status in statuses):
                return "partial"
            return "failed"

        collection_states: dict[str, CollectionStatus] = {
            "repository": endpoint_state(f"/repos/{owner}/{repo}"),
            "retention_settings": endpoint_state(
                f"/repos/{owner}/{repo}/actions/permissions/artifact-and-log-retention"
            ),
            "workflow_runs": endpoint_state(f"/repos/{owner}/{repo}/actions/runs"),
        }
        if runs:
            collection_states["artifacts"] = endpoint_state(
                f"/repos/{owner}/{repo}/actions/runs/", prefix=True
            )
        if include_checks:
            collection_states["check_runs"] = endpoint_state("/check-runs", prefix=True)
        else:
            collection_states["check_runs"] = "not_requested"
        if include_statuses:
            collection_states["commit_statuses"] = endpoint_state("/status", prefix=True)
        else:
            collection_states["commit_statuses"] = "not_requested"
        states = tuple(sorted(collection_states.items()))
        if any(status == "failed" for _, status in states):
            collection_status: CollectionStatus = "failed"
        elif any(status in {"partial", "unknown"} for _, status in states):
            collection_status = "partial"
        else:
            collection_status = "complete"
        unknown_objects = sum(1 for obj in objects.values() if obj.retention_status == "unknown")
        snapshot = InventorySnapshot(
            snapshot_id=f"github-actions:{owner}/{repo}:{now.isoformat()}",
            captured_at=now,
            now=now,
            policy_version=policy_version,
            objects=tuple(objects.values()),
            edges=tuple(edges),
            releases=releases,
            api_requests=len(self.request_log),
            failed_requests=sum(
                1
                for entry in self.request_log
                if entry.get("status") is None or entry.get("status", 0) >= 400
            ),
            unknown_objects=unknown_objects,
            collection_status=collection_status,
            collection_states=states,
        )
        return GitHubActionsCollection(
            snapshot=snapshot,
            repository=repository,
            retention_settings=retention if isinstance(retention, dict) else None,
            request_log=tuple(self.request_log),
            warnings=tuple(dict.fromkeys(warnings)),
        )
