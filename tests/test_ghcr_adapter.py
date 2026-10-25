import json
from urllib.parse import urlparse
from retention_governance.providers.github_actions import HttpResponse
from retention_governance.providers.ghcr import GHCRClient
from retention_governance.planner import plan_retention


class RegistryTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, headers):
        self.calls.append((url, headers))
        path = urlparse(url).path
        status, payload, response_headers = self.responses.get(path, (404, {}, {}))
        return HttpResponse(status, response_headers, json.dumps(payload).encode())


def test_index_and_children_become_dependency_graph_objects():
    responses = {
        '/v2/acme/model/manifests/latest': (200, {
            'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': [
                {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:amd64', 'size': 100},
                {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:arm64', 'size': 101},
            ],
        }, {'docker-content-digest': 'sha256:index'}),
        '/v2/acme/model/manifests/sha256:amd64': (200, {'mediaType': 'application/vnd.oci.image.manifest.v1+json'}, {'docker-content-digest': 'sha256:amd64'}),
        '/v2/acme/model/manifests/sha256:arm64': (200, {'mediaType': 'application/vnd.oci.image.manifest.v1+json'}, {'docker-content-digest': 'sha256:arm64'}),
    }
    transport = RegistryTransport(responses)
    collection = GHCRClient(token='registry-secret', transport=transport).collect(
        'acme', 'model', 'latest', release_id='release-oci'
    )
    objects = collection.snapshot.object_map()
    assert objects['ghcr:acme/model:digest:sha256:index'].object_type == 'oci-index'
    assert objects['ghcr:acme/model:digest:sha256:amd64'].object_type == 'oci-manifest'
    assert len(collection.snapshot.edges) == 2
    assert collection.missing_references == ()
    assert 'retention_metadata_unavailable' in collection.warnings
    assert all('registry-secret' not in str(entry) for entry in collection.request_log)
    assert all(call[1]['Authorization'] == 'Bearer registry-secret' for call in transport.calls)


def test_missing_child_is_explicit_not_assumed_retained():
    responses = {
        '/v2/acme/model/manifests/latest': (200, {
            'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:missing'}],
        }, {'docker-content-digest': 'sha256:index'}),
    }
    collection = GHCRClient(transport=RegistryTransport(responses)).collect('acme', 'model', 'latest')
    assert collection.missing_references == ('ghcr:acme/model:digest:sha256:missing',)
    assert 'child_manifest_unavailable' in collection.warnings
    assert collection.snapshot.failed_requests == 1


def test_unverified_children_are_visible_when_fetch_is_disabled():
    responses = {
        '/v2/acme/model/manifests/latest': (200, {
            'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:child', 'size': 42}],
        }, {'docker-content-digest': 'sha256:index'}),
    }
    collection = GHCRClient(transport=RegistryTransport(responses)).collect(
        'acme', 'model', 'latest', fetch_children=False
    )
    child = collection.snapshot.object_map()['ghcr:acme/model:digest:sha256:child']
    assert child.retention_status == 'unknown'
    assert 'child_manifests_unverified' in collection.warnings
    assert collection.snapshot.api_requests == 1


def test_missing_child_flows_into_hold_for_review_plan():
    responses = {
        '/v2/acme/model/manifests/latest': (200, {
            'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:missing'}],
        }, {'docker-content-digest': 'sha256:index'}),
    }
    collection = GHCRClient(transport=RegistryTransport(responses)).collect(
        'acme', 'model', 'latest', release_id='release-oci'
    )
    plan = plan_retention(collection.snapshot)
    action_map = {action.object_id: action.action for action in plan.actions}
    assert action_map['ghcr:acme/model:digest:sha256:missing'] == 'HOLD_FOR_REVIEW'
