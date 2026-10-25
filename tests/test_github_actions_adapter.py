from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from retention_governance.providers.github_actions import GitHubActionsClient, HttpResponse


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, headers):
        self.calls.append((url, headers))
        path = urlparse(url).path
        query = parse_qs(urlparse(url).query)
        page = int(query.get('page', ['1'])[0])
        key = (path, page)
        response = self.responses.get(key) or self.responses.get((path, None))
        if response is None:
            return HttpResponse(404, {}, b'{}')
        if isinstance(response, Exception):
            raise response
        return response


def response(payload, status=200):
    import json
    return HttpResponse(status, {'x-ratelimit-remaining': '4999'}, json.dumps(payload).encode())


def test_read_only_adapter_normalizes_runs_artifacts_and_dependencies():
    responses = {
        ('/repos/acme/demo', None): response({'private': True, 'visibility': 'private'}),
        ('/repos/acme/demo/actions/permissions/artifact-and-log-retention', None): response({'days': 90, 'maximum_days': 400}),
        ('/repos/acme/demo/actions/runs', 1): response({'workflow_runs': [{
            'id': 7,
            'created_at': '2026-10-01T00:00:00Z',
            'head_sha': 'abc123',
            'html_url': 'https://github.com/acme/demo/actions/runs/7',
        }]}),
        ('/repos/acme/demo/actions/runs/7/artifacts', 1): response({'artifacts': [{
            'id': 8,
            'created_at': '2026-10-02T00:00:00Z',
            'expires_at': '2026-12-01T00:00:00Z',
            'expired': False,
            'size_in_bytes': 123,
            'digest': 'sha256:artifact',
            'url': 'https://api.github.com/repos/acme/demo/actions/artifacts/8',
        }]}),
    }
    transport = FakeTransport(responses)
    collection = GitHubActionsClient(token='secret-token', transport=transport).collect(
        'acme', 'demo',
        now=datetime(2026, 10, 25, tzinfo=timezone.utc),
        warning_days=45,
        release_roots={'release-7': ('github:acme/demo:workflow-run:7',)},
        audit_horizon=datetime(2027, 10, 25, tzinfo=timezone.utc),
    )
    snapshot = collection.snapshot
    objects = snapshot.object_map()
    assert objects['github:acme/demo:workflow-run:7'].expires_at.isoformat() == '2026-12-30T00:00:00+00:00'
    assert objects['github:acme/demo:artifact:8'].retention_status == 'expiring'
    assert any(edge.prerequisite_id.endswith(':artifact:8') for edge in snapshot.edges) is False
    assert any(edge.dependent_id.endswith(':artifact:8') for edge in snapshot.edges)
    assert snapshot.api_requests == 4
    assert snapshot.failed_requests == 0
    assert snapshot.collection_status == 'complete'
    assert snapshot.collection_state_map()['workflow_runs'] == 'complete'
    assert snapshot.releases[0].audit_horizon.isoformat() == '2027-10-25T00:00:00+00:00'
    assert objects['github:acme/demo:workflow-run:7'].expiration_source == 'derived'
    assert not objects['github:acme/demo:workflow-run:7'].survives_until(snapshot.releases[0].audit_horizon)
    assert any(call[1].get('Authorization') == 'Bearer secret-token' for call in transport.calls)
    assert all('secret-token' not in str(entry) for entry in collection.request_log)


def test_failed_settings_request_is_visible_and_retention_becomes_unknown():
    responses = {
        ('/repos/acme/demo', None): response({'private': False, 'visibility': 'public'}),
        ('/repos/acme/demo/actions/permissions/artifact-and-log-retention', None): response({}, status=403),
        ('/repos/acme/demo/actions/runs', 1): response({'workflow_runs': []}),
    }
    transport = FakeTransport(responses)
    collection = GitHubActionsClient(transport=transport).collect('acme', 'demo')
    assert collection.retention_settings is None
    assert 'retention_settings_unavailable' in collection.warnings
    assert 'check_runs_not_collected' in collection.warnings
    assert collection.snapshot.failed_requests == 1
    assert collection.snapshot.api_requests == 3
    assert collection.request_log[1]['error'] == 'http_error'


def test_pagination_continues_at_full_page_and_stops_on_short_page():
    first_page = [{'id': index, 'created_at': '2026-10-01T00:00:00Z'} for index in range(100)]
    responses = {
        ('/repos/acme/demo', None): response({}),
        ('/repos/acme/demo/actions/permissions/artifact-and-log-retention', None): response({'days': 90}),
        ('/repos/acme/demo/actions/runs', 1): response({'workflow_runs': first_page}),
        ('/repos/acme/demo/actions/runs', 2): response({'workflow_runs': [{'id': 101, 'created_at': '2026-10-01T00:00:00Z'}]}),
    }
    transport = FakeTransport(responses)
    collection = GitHubActionsClient(transport=transport).collect('acme', 'demo')
    run_calls = [call for call in transport.calls if '/actions/runs?' in call[0]]
    assert len(run_calls) == 2
    assert len([obj for obj in collection.snapshot.objects if obj.object_type == 'workflow-run']) == 101


def test_failed_second_page_marks_workflow_collection_partial():
    first_page = [{'id': index, 'created_at': '2026-10-01T00:00:00Z'} for index in range(100)]
    responses = {
        ('/repos/acme/demo', None): response({}),
        ('/repos/acme/demo/actions/permissions/artifact-and-log-retention', None): response({'days': 90}),
        ('/repos/acme/demo/actions/runs', 1): response({'workflow_runs': first_page}),
        ('/repos/acme/demo/actions/runs', 2): response({}, status=500),
    }
    class PaginationTransport(FakeTransport):
        def get(self, url, headers):
            if '/actions/runs/' in url and '/artifacts?' in url:
                return response({'artifacts': []})
            return super().get(url, headers)

    collection = GitHubActionsClient(transport=PaginationTransport(responses)).collect('acme', 'demo')
    assert collection.snapshot.collection_state_map()['workflow_runs'] == 'partial'
    assert collection.snapshot.collection_status == 'partial'
    assert collection.snapshot.failed_requests == 1


def test_optional_check_runs_and_commit_statuses_are_normalized():
    responses = {
        ('/repos/acme/demo', None): response({'visibility': 'public'}),
        ('/repos/acme/demo/actions/permissions/artifact-and-log-retention', None): response({'days': 90}),
        ('/repos/acme/demo/actions/runs', 1): response({'workflow_runs': [{
            'id': 7, 'created_at': '2026-10-01T00:00:00Z', 'head_sha': 'abc123'
        }]}),
        ('/repos/acme/demo/actions/runs/7/artifacts', 1): response({'artifacts': []}),
        ('/repos/acme/demo/commits/abc123/check-runs', 1): response({'check_runs': [{
            'id': 21, 'started_at': '2026-10-02T00:00:00Z', 'html_url': 'https://github.com/acme/demo/runs/21'
        }]}),
        ('/repos/acme/demo/commits/abc123/status', 1): response([{
            'id': 22, 'created_at': '2026-10-03T00:00:00Z', 'target_url': 'https://ci.example/status/22'
        }]),
    }
    transport = FakeTransport(responses)
    collection = GitHubActionsClient(transport=transport).collect(
        'acme', 'demo',
        include_checks=True,
        include_statuses=True,
        now=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    object_types = [obj.object_type for obj in collection.snapshot.objects]
    assert 'check-run' in object_types
    assert 'commit-status' in object_types
    assert 'check_runs_not_collected' not in collection.warnings
    assert 'commit_statuses_not_collected' not in collection.warnings
    assert any(edge.prerequisite_id.endswith(':commit:abc123') for edge in collection.snapshot.edges)
