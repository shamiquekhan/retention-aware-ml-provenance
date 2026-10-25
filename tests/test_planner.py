from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from retention_governance.benchmark import load_cases
from retention_governance.planner import plan_retention
from retention_governance.schema import InventorySnapshot

ROOT=Path(__file__).resolve().parents[1]

def actions(case_id):
    case=next(case for case in load_cases(ROOT/'scenarios/pilot.json') if case['case_id']==case_id)
    plan=plan_retention(InventorySnapshot.from_dict(case['inventory']))
    return {action.object_id: action for action in plan.actions}, plan

def test_transitive_oci_children_are_preserved():
    action_map, _ = actions('complete_multiarch')
    assert action_map['child-amd64'].action == 'PRESERVE_DEPENDENCY'
    assert action_map['child-arm64'].action == 'PRESERVE_DEPENDENCY'
    assert action_map['unused-build'].action == 'CANDIDATE_FOR_DELETION'

def test_expiring_required_evidence_is_archived_not_deleted():
    action_map, _ = actions('expiring_required_evidence')
    assert action_map['workflow-expiring'].action == 'ARCHIVE'
    assert action_map['workflow-expiring'].required

def test_verified_archive_satisfies_required_evidence():
    action_map, _ = actions('verified_archive')
    assert action_map['workflow-archived'].action == 'PRESERVE_DEPENDENCY'

def test_unknown_dependency_holds_for_review():
    action_map, plan = actions('unknown_manifest_dependency')
    assert action_map['missing-child'].action == 'HOLD_FOR_REVIEW'
    assert 'missing-child' in plan.missing_dependencies

def test_shared_digest_does_not_make_unreferenced_tag_required():
    action_map, _ = actions('shared_digest')
    assert action_map['shared-child'].action == 'PRESERVE_DEPENDENCY'
    assert action_map['tag-only'].action == 'CANDIDATE_FOR_DELETION'


def test_unverified_archive_holds_required_evidence():
    case = next(case for case in load_cases(ROOT/'scenarios/pilot.json') if case['case_id'] == 'expiring_required_evidence')
    inventory = dict(case['inventory'])
    inventory['objects'] = [
        {**item, 'archive': {'status': 'unverified', 'digest': 'sha256:wrong', 'verified_at': None, 'accessible': False}}
        if item['object_id'] == 'workflow-expiring' else item
        for item in inventory['objects']
    ]
    action_map = {action.object_id: action for action in plan_retention(InventorySnapshot.from_dict(inventory)).actions}
    assert action_map['workflow-expiring'].action == 'HOLD_FOR_REVIEW'


def test_unknown_expiration_is_not_treated_as_indefinite_retention():
    case = next(case for case in load_cases(ROOT/'scenarios/pilot.json') if case['case_id'] == 'complete_multiarch')
    inventory = dict(case['inventory'])
    inventory['objects'] = [
        {**item, 'expires_at': None, 'retention_status': 'available'}
        if item['object_id'] == 'workflow-complete' else item
        for item in inventory['objects']
    ]
    action_map = {action.object_id: action for action in plan_retention(InventorySnapshot.from_dict(inventory)).actions}
    assert action_map['workflow-complete'].action == 'HOLD_FOR_REVIEW'


def test_planning_is_deterministic_for_same_snapshot():
    case = load_cases(ROOT/'scenarios/pilot.json')[0]
    snapshot = InventorySnapshot.from_dict(case['inventory'])
    first = plan_retention(snapshot).as_dict()
    second = plan_retention(snapshot).as_dict()
    assert first == second


def test_longer_horizon_cannot_improve_required_retention_action():
    case = next(case for case in load_cases(ROOT/'scenarios/pilot.json') if case['case_id'] == 'complete_multiarch')
    snapshot = InventorySnapshot.from_dict(case['inventory'])
    short_release = replace(snapshot.releases[0], audit_horizon=snapshot.now + timedelta(days=10))
    long_release = replace(snapshot.releases[0], audit_horizon=snapshot.now + timedelta(days=500))
    short = plan_retention(replace(snapshot, releases=(short_release,)))
    long = plan_retention(replace(snapshot, releases=(long_release,)))
    severity = {'PRESERVE': 0, 'PRESERVE_DEPENDENCY': 0, 'ARCHIVE': 1, 'HOLD_FOR_REVIEW': 2, 'CANDIDATE_FOR_DELETION': 3}
    short_actions = {action.object_id: severity[action.action] for action in short.actions}
    long_actions = {action.object_id: severity[action.action] for action in long.actions}
    for object_id in short_actions:
        assert long_actions[object_id] >= short_actions[object_id]
