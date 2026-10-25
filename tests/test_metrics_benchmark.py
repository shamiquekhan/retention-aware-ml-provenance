from pathlib import Path
from retention_governance.benchmark import aggregate_metrics, benchmark_hash, evaluate_benchmark, load_cases
from retention_governance.metrics import evaluate_plan
from retention_governance.planner import plan_retention
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
