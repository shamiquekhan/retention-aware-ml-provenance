#!/usr/bin/env python3
"""Merge provider inventory outputs into one dry-run provenance graph."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from retention_governance.merge import CrossServiceReference, attach_references, merge_snapshots
from retention_governance.schema import InventorySnapshot, ReleaseRequirement


def load_snapshot(path: Path) -> InventorySnapshot:
    payload=json.loads(path.read_text())
    return InventorySnapshot.from_dict(payload['snapshot'] if 'snapshot' in payload else payload)


def main() -> int:
    parser=argparse.ArgumentParser(description='Merge read-only provider inventories; never mutates a provider.')
    parser.add_argument('--input', action='append', type=Path, required=True, help='Provider inventory JSON; repeat for each service.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--references', type=Path, help='JSON list of cross-service edges.')
    parser.add_argument('--releases', type=Path, help='JSON list of release requirements.')
    parser.add_argument('--snapshot-id', default='cross-service-merged')
    args=parser.parse_args()
    snapshots=[load_snapshot(path) for path in args.input]
    releases=[]
    if args.releases:
        releases=[ReleaseRequirement.from_dict(item) for item in json.loads(args.releases.read_text())]
    merged=merge_snapshots(snapshots, snapshot_id=args.snapshot_id, releases=releases)
    missing=[]
    if args.references:
        refs=[CrossServiceReference(**item) for item in json.loads(args.references.read_text())]
        result=attach_references(merged, refs)
        merged=result.snapshot
        missing=list(result.missing_references)
    payload={'snapshot': merged.as_dict(), 'missing_references': missing, 'read_only': True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'output':str(args.output), 'objects':len(merged.objects), 'edges':len(merged.edges), 'missing_references':missing}, indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
