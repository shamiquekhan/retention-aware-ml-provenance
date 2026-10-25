from pathlib import Path
from dataclasses import replace
from retention_governance.baselines import baseline_plan
from retention_governance.benchmark import aggregate_metrics, benchmark_hash, evaluate_benchmark, load_cases
from retention_governance.metrics import evaluate_plan
from retention_governance.planner import DecisionPlan, PlanAction, inventory_hash, plan_retention
from retention_governance.schema import InventorySnapshot

ROOT=Path(__file__).resolve().parents[1]

def test_benchmark_has_explicit_metric_denominators():
    report=evaluate_benchmark(ROOT/'scenarios/pilot.json')
    assert report['case_count'] == 5
    for case in report['cases']:
        metrics=case['strategies']['dependency_aware']['metrics']
        assert 'numerator' in metrics['unsafe_deletion_proposal_rate']
        assert 'denominator' in metrics['current_evidence_chain_completeness']
        assert 'denominator' in metrics['inventory_coverage']
        assert 'retention_overhead_byte_days' in metrics

def test_dependency_aware_planner_does_not_propose_unsafe_deletion_in_pilot():
    for case in load_cases(ROOT/'scenarios/pilot.json'):
        snapshot=InventorySnapshot.from_dict(case['inventory'])
        metrics=evaluate_plan(snapshot, plan_retention(snapshot))
        assert metrics.unsafe_deletion_proposals == 0


def test_benchmark_report_contains_manifest_hash_and_aggregates():
    report = evaluate_benchmark(ROOT/'scenarios/pilot.json')
    assert len(report['benchmark_hash']) == 64
    assert set(report['strategies']) == {'native', 'independent_ttl', 'conservative', 'dependency_aware'}
    aggregate = report['strategies']['dependency_aware']
    assert aggregate['current_evidence_chain_completeness']['denominator'] == 5
    assert aggregate['unsafe_deletion_proposal_rate']['numerator'] == 0


def test_required_deletion_cannot_count_as_projected_complete():
    case = next(case for case in load_cases(ROOT / 'scenarios/pilot.json') if case['case_id'] == 'complete_multiarch')
    snapshot = InventorySnapshot.from_dict(case['inventory'])
    normal = plan_retention(snapshot)
    actions = tuple(
        PlanAction('CANDIDATE_FOR_DELETION', 'workflow-complete', 'deliberately unsafe test plan', required=True)
        if action.object_id == 'workflow-complete' else action
        for action in normal.actions
    )
    unsafe_plan = DecisionPlan(
        planner_version='test',
        policy_version=snapshot.policy_version,
        inventory_hash=inventory_hash(snapshot),
        generated_at=snapshot.captured_at,
        actions=actions,
        missing_dependencies=(),
    )
    metrics = evaluate_plan(snapshot, unsafe_plan)
    assert metrics.planned_complete_releases == 0
    assert metrics.unsafe_deletion_proposals == 1


def test_proposed_archive_is_resolution_coverage_not_verified_completeness():
    case = next(case for case in load_cases(ROOT / 'scenarios/pilot.json') if case['case_id'] == 'expiring_required_evidence')
    snapshot = InventorySnapshot.from_dict(case['inventory'])
    metrics = evaluate_plan(snapshot, plan_retention(snapshot))
    assert metrics.planned_complete_releases == 0
    assert metrics.resolved_gap_objects >= 1
    assert metrics.as_dict()['planned_resolution_coverage']['rate'] == 1.0


def test_baselines_use_shared_horizon_and_conservative_retains_all_objects():
    case = next(case for case in load_cases(ROOT / 'scenarios/pilot.json') if case['case_id'] == 'expiring_required_evidence')
    snapshot = InventorySnapshot.from_dict(case['inventory'])
    independent = {action.object_id: action for action in baseline_plan(snapshot, 'independent_ttl').actions}
    conservative = {action.object_id: action for action in baseline_plan(snapshot, 'conservative').actions}
    assert independent['workflow-expiring'].action == 'CANDIDATE_FOR_DELETION'
    assert all(action.action == 'PRESERVE' for action in conservative.values())


def test_incomplete_inventory_cannot_report_complete_evidence():
    case = load_cases(ROOT / 'scenarios/pilot.json')[0]
    snapshot = InventorySnapshot.from_dict(case['inventory'])
    partial = replace(snapshot, collection_status='partial', collection_states=(('workflow_runs', 'partial'),))
    metrics = evaluate_plan(partial, plan_retention(partial))
    assert metrics.current_complete_releases == 0
    assert metrics.planned_complete_releases == 0


def test_expanded_benchmark_covers_inventory_and_archive_variants():
    report = evaluate_benchmark(ROOT / 'scenarios/expanded.json')
    assert report['case_count'] == 16
    descriptions = {case['description'] for case in report['cases']}
    assert any('partial_inventory' in description for description in descriptions)
    assert any('missing_child' in description for description in descriptions)
    assert any('unverified_archive' in description for description in descriptions)
