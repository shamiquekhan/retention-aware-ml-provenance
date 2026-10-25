import json
from pathlib import Path
import pytest
from retention_governance.benchmark import load_cases
from retention_governance.graph import EvidenceGraph
from retention_governance.schema import InventorySnapshot

ROOT=Path(__file__).resolve().parents[1]


def test_pilot_objects_and_edges_have_unique_ids_and_closure():
    for case in load_cases(ROOT/'scenarios/pilot.json'):
        snapshot=InventorySnapshot.from_dict(case['inventory'])
        graph=EvidenceGraph(snapshot)
        closures=graph.closures_for_releases()
        assert closures
        assert all(not closure.missing_ids for closure in closures.values()) or case['case_id']=='unknown_manifest_dependency'


def test_duplicate_object_ids_fail():
    case=load_cases(ROOT/'scenarios/pilot.json')[0]
    snapshot=dict(case['inventory'])
    snapshot['objects']=snapshot['objects']+[snapshot['objects'][0]]
    with pytest.raises(ValueError, match='duplicate evidence object ID'):
        InventorySnapshot.from_dict(snapshot).object_map()


def test_missing_dependency_is_explicit():
    case=next(case for case in load_cases(ROOT/'scenarios/pilot.json') if case['case_id']=='unknown_manifest_dependency')
    closure=EvidenceGraph(InventorySnapshot.from_dict(case['inventory'])).closures_for_releases()['release-unknown']
    assert 'missing-child' in closure.missing_ids


def test_generated_inventory_is_reproducible():
    from retention_governance.generator import generate_inventory
    from retention_governance.planner import inventory_hash, plan_retention
    first = generate_inventory(17)
    second = generate_inventory(17)
    assert inventory_hash(first) == inventory_hash(second)
    assert plan_retention(first).as_dict() == plan_retention(second).as_dict()
    assert inventory_hash(first) != inventory_hash(generate_inventory(18))
