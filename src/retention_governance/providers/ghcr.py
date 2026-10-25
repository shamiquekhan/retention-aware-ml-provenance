"""Read-only GHCR/OCI manifest dependency adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from urllib.parse import quote

from ..schema import EvidenceEdge, EvidenceObject, InventorySnapshot, ReleaseRequirement
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
        registry: str = "ghcr.io",
        transport: Transport,
    ) -> None:
        self.registry = registry.rstrip("/")
        self.transport = transport
        self._auth_header = f"Bearer {token}" if token else None
        self.request_log: list[dict[str, Any]] = []

    def _get_json(self, path: str) -> tuple[Any | None, dict[str, str]]:
        url = f"https://{self.registry}{path}"
        headers = {
            "Accept": OCI_ACCEPT,
            "User-Agent": "retention-aware-ml-provenance/0.1",
        }
        if self._auth_header:
            headers["Authorization"] = self._auth_header
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
        if not 200 <= response.status < 300:
            entry["error"] = "http_error"
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
        fetch_children: bool = True,
    ) -> GHCRCollection:
        now = now or datetime.now(timezone.utc)
        package_path = quote(f"{owner}/{package}", safe="/")
        reference_path = quote(reference, safe="@:+")
        payload, headers = self._get_json(f"/v2/{package_path}/manifests/{reference_path}")
        warnings: list[str] = []
        missing: list[str] = []
        objects: dict[str, EvidenceObject] = {}
        edges: list[EvidenceEdge] = []
        policy_version = "ghcr-oci:0.1"

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
            seen: set[str] = set()
            while pending:
                parent_id, descriptor, depth = pending.pop(0)
                child_digest = descriptor.get("digest")
                if not child_digest or child_digest in seen:
                    if not child_digest:
                        warnings.append("child_digest_unavailable")
                    continue
                seen.add(child_digest)
                child_id = f"ghcr:{owner}/{package}:digest:{child_digest}"
                media_type = str(descriptor.get("mediaType", ""))
                child_type = "oci-index" if "index" in media_type or "manifest.list" in media_type else "oci-manifest"
                edges.append(EvidenceEdge(parent_id, child_id, "child_of"))
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

        releases = ()
        if release_id:
            releases = (ReleaseRequirement(release_id, now, (root_id,)),)
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
        )
        return GHCRCollection(
            snapshot=snapshot,
            request_log=tuple(self.request_log),
            warnings=tuple(dict.fromkeys(warnings)),
            missing_references=tuple(dict.fromkeys(missing)),
            root_object_id=root_id if isinstance(payload, dict) else None,
        )
