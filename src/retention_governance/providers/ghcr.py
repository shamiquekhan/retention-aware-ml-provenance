"""Read-only GHCR/OCI manifest dependency adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote, urlencode

from ..schema import (
    CollectionStatus,
    EvidenceEdge,
    EvidenceObject,
    InventorySnapshot,
    ReleaseRequirement,
)
from .github_actions import HttpResponse, Transport


OCI_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


@dataclass(frozen=True)
class GHCRCollection:
    snapshot: InventorySnapshot
    request_log: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    missing_references: tuple[str, ...]
    root_object_id: str | None


class GHCRClient:
    """Fetch OCI manifests and transitive index children without mutation."""

    def __init__(
        self,
        *,
        token: str | None = None,
        username: str | None = None,
        registry: str = "ghcr.io",
        transport: Transport,
    ) -> None:
        self.registry = registry.rstrip("/")
        self.transport = transport
        self.token = token
        self.username = username
        self._registry_token: str | None = None
        self._repository: str | None = None
        self.request_log: list[dict[str, Any]] = []

    @staticmethod
    def _challenge_parameters(value: str | None) -> dict[str, str]:
        if not value or not value.lower().startswith("bearer "):
            return {}
        return {
            key: match
            for key, match in re.findall(r'(\w+)="([^"]*)"', value)
        }

    def _exchange_registry_token(self, challenge: str | None) -> str | None:
        parameters = self._challenge_parameters(challenge)
        realm = parameters.get("realm")
        if not realm:
            return None
        query = {
            key: value
            for key, value in {
                "service": parameters.get("service"),
                "scope": parameters.get("scope") or (
                    f"repository:{self._repository}:pull" if self._repository else None
                ),
            }.items()
            if value
        }
        token_url = f"{realm}?{urlencode(query)}" if query else realm
        headers = {"Accept": "application/json", "User-Agent": "retention-aware-ml-provenance/0.2"}
        if self.token:
            credentials = f"{self.username or ''}:{self.token}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(credentials).decode('ascii')}"
        try:
            response = self.transport.get(token_url, headers)
        except Exception as error:  # noqa: BLE001 - provider failure is inventory data
            self.request_log.append({"url": token_url, "status": None, "error": type(error).__name__})
            return None
        entry = {"url": token_url, "status": response.status, "auth_exchange": True}
        self.request_log.append(entry)
        if not 200 <= response.status < 300:
            entry["error"] = "auth_exchange_failed"
            return None
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            entry["error"] = "invalid_auth_exchange_response"
            return None
        exchanged = payload.get("token") or payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(exchanged, str) or not exchanged:
            entry["error"] = "auth_token_missing"
            return None
        return exchanged

    def _get_json(self, path: str) -> tuple[Any | None, dict[str, str]]:
        url = f"https://{self.registry}{path}"
        headers = {
            "Accept": OCI_ACCEPT,
            "User-Agent": "retention-aware-ml-provenance/0.2",
        }
        if self._registry_token:
            headers["Authorization"] = f"Bearer {self._registry_token}"
        try:
            response = self.transport.get(url, headers)
        except Exception as error:  # noqa: BLE001 - provider failure is inventory data
            self.request_log.append({"url": url, "status": None, "error": type(error).__name__})
            return None, {}
        entry = {"url": url, "status": response.status}
        for name in ("docker-content-digest", "ratelimit-remaining", "ratelimit-reset"):
            if name in response.headers:
                entry[name.replace("-", "_")] = response.headers[name]
        self.request_log.append(entry)
        if response.status == 401 and self.token:
            exchanged = self._exchange_registry_token(response.headers.get("www-authenticate"))
            if exchanged:
                self._registry_token = exchanged
                retry_headers = dict(headers)
                retry_headers["Authorization"] = f"Bearer {exchanged}"
                try:
                    response = self.transport.get(url, retry_headers)
                except Exception as error:  # noqa: BLE001 - provider failure is inventory data
                    self.request_log.append({"url": url, "status": None, "error": type(error).__name__})
                    return None, {}
                retry_entry = {"url": url, "status": response.status, "auth_retry": True}
                self.request_log.append(retry_entry)
        if not 200 <= response.status < 300:
            self.request_log[-1]["error"] = "http_error"
            return None, response.headers
        try:
            return json.loads(response.body.decode("utf-8")), response.headers
        except (UnicodeDecodeError, json.JSONDecodeError):
            entry["error"] = "invalid_json"
            return None, response.headers

    def collect(
        self,
        owner: str,
        package: str,
        reference: str,
        *,
        now: datetime | None = None,
        release_id: str | None = None,
        audit_horizon: datetime | None = None,
        release_requirements: tuple[ReleaseRequirement, ...] = (),
        fetch_children: bool = True,
    ) -> GHCRCollection:
        now = now or datetime.now(timezone.utc)
        package_path = quote(f"{owner}/{package}", safe="/")
        reference_path = quote(reference, safe="@:+")
        self._repository = f"{owner}/{package}"
        payload, headers = self._get_json(f"/v2/{package_path}/manifests/{reference_path}")
        warnings: list[str] = []
        missing: list[str] = []
        objects: dict[str, EvidenceObject] = {}
        edges: list[EvidenceEdge] = []
        policy_version = "ghcr-oci:0.2"

        digest = headers.get("docker-content-digest")
        if digest is None and reference.startswith("sha256:"):
            digest = reference
        if digest is None:
            warnings.append("manifest_digest_unavailable")
        if payload is None:
            missing.append(f"ghcr:{owner}/{package}:reference:{reference}")
        root_id = (
            f"ghcr:{owner}/{package}:digest:{digest}"
            if digest
            else f"ghcr:{owner}/{package}:reference:{reference}"
        )
        if isinstance(payload, dict):
            root_type = "oci-index" if isinstance(payload.get("manifests"), list) else "oci-manifest"
            objects[root_id] = EvidenceObject(
                object_id=root_id,
                provider="ghcr",
                object_type=root_type,
                created_at=now,
                expires_at=None,
                retention_status="unknown",
                digest=digest,
                size_bytes=None,
                source_uri=f"https://{self.registry}/v2/{owner}/{package}/manifests/{reference}",
                policy_version=policy_version,
            )
            warnings.append("retention_metadata_unavailable")
            descriptors = payload.get("manifests", []) if root_type == "oci-index" else []
            pending = [(root_id, descriptor, 0) for descriptor in descriptors if isinstance(descriptor, dict)]
            fetched_digests: set[str] = set()
            while pending:
                parent_id, descriptor, depth = pending.pop(0)
                child_digest = descriptor.get("digest")
                if not child_digest:
                    descriptor_hash = hashlib.sha256(
                        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()[:16]
                    unresolved_id = f"ghcr:{owner}/{package}:unresolved:{descriptor_hash}"
                    edges.append(EvidenceEdge(parent_id, unresolved_id, "child_of"))
                    missing.append(unresolved_id)
                    warnings.append("child_digest_unavailable")
                    continue
                child_id = f"ghcr:{owner}/{package}:digest:{child_digest}"
                media_type = str(descriptor.get("mediaType", ""))
                child_type = "oci-index" if "index" in media_type or "manifest.list" in media_type else "oci-manifest"
                edges.append(EvidenceEdge(parent_id, child_id, "child_of"))
                if child_digest in fetched_digests:
                    continue
                fetched_digests.add(child_digest)
                if not fetch_children:
                    objects[child_id] = EvidenceObject(
                        object_id=child_id,
                        provider="ghcr",
                        object_type=child_type,
                        created_at=now,
                        expires_at=None,
                        retention_status="unknown",
                        digest=child_digest,
                        size_bytes=descriptor.get("size"),
                        source_uri=f"https://{self.registry}/v2/{owner}/{package}/manifests/{child_digest}",
                        policy_version=policy_version,
                    )
                    warnings.append("child_manifests_unverified")
                    continue
                child_payload, child_headers = self._get_json(
                    f"/v2/{package_path}/manifests/{quote(child_digest, safe='@:+')}"
                )
                if child_payload is None:
                    missing.append(child_id)
                    warnings.append("child_manifest_unavailable")
                    continue
                objects[child_id] = EvidenceObject(
                    object_id=child_id,
                    provider="ghcr",
                    object_type=child_type,
                    created_at=now,
                    expires_at=None,
                    retention_status="unknown",
                    digest=child_headers.get("docker-content-digest", child_digest),
                    size_bytes=descriptor.get("size"),
                    source_uri=f"https://{self.registry}/v2/{owner}/{package}/manifests/{child_digest}",
                    policy_version=policy_version,
                )
                if child_type == "oci-index":
                    for nested in child_payload.get("manifests", []) if isinstance(child_payload, dict) else []:
                        if isinstance(nested, dict):
                            pending.append((child_id, nested, depth + 1))

        releases = tuple(release_requirements)
        if release_id:
            if audit_horizon is None:
                warnings.append("release_audit_horizon_required")
            else:
                releases += (ReleaseRequirement(release_id, audit_horizon, (root_id,)),)
        child_failed = any(item in missing for item in objects if item.startswith("ghcr:"))
        collection_states: tuple[tuple[str, CollectionStatus], ...]
        if payload is None:
            collection_states = (("root_manifest", "failed"),)
            collection_status: CollectionStatus = "failed"
        elif not fetch_children:
            collection_states = (("root_manifest", "complete"), ("child_manifests", "unknown"))
            collection_status = "unknown"
        elif child_failed or missing:
            collection_states = (("root_manifest", "complete"), ("child_manifests", "partial"))
            collection_status = "partial"
        else:
            collection_states = (("root_manifest", "complete"), ("child_manifests", "complete"))
            collection_status = "complete"
        snapshot = InventorySnapshot(
            snapshot_id=f"ghcr:{owner}/{package}:{reference}:{now.isoformat()}",
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
            unknown_objects=sum(1 for obj in objects.values() if obj.retention_status == "unknown"),
            collection_status=collection_status,
            collection_states=collection_states,
        )
        return GHCRCollection(
            snapshot=snapshot,
            request_log=tuple(self.request_log),
            warnings=tuple(dict.fromkeys(warnings)),
            missing_references=tuple(dict.fromkeys(missing)),
            root_object_id=root_id if isinstance(payload, dict) else None,
        )
