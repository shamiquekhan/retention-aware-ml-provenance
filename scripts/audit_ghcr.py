#!/usr/bin/env python3
"""Run a read-only GHCR/OCI manifest dependency audit."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from retention_governance.providers.ghcr import GHCRClient
from retention_governance.providers.github_actions import UrllibTransport


def main() -> int:
    parser=argparse.ArgumentParser(description='Read-only GHCR manifest audit; never mutates registry state.')
    parser.add_argument('--owner', required=True)
    parser.add_argument('--package', required=True)
    parser.add_argument('--reference', required=True, help='Tag or immutable digest reference.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release-id')
    parser.add_argument('--token-env', default='GITHUB_TOKEN')
    parser.add_argument('--no-fetch-children', action='store_true')
    args=parser.parse_args()
    token=os.environ.get(args.token_env)
    collection=GHCRClient(token=token, transport=UrllibTransport()).collect(
        args.owner, args.package, args.reference,
        release_id=args.release_id,
        fetch_children=not args.no_fetch_children,
    )
    payload={
        'request_log': list(collection.request_log),
        'warnings': list(collection.warnings),
        'missing_references': list(collection.missing_references),
        'root_object_id': collection.root_object_id,
        'snapshot': collection.snapshot.as_dict(),
        'read_only': True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'output':str(args.output), 'objects':len(collection.snapshot.objects), 'requests':collection.snapshot.api_requests, 'failures':collection.snapshot.failed_requests}, indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
