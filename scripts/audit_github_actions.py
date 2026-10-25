#!/usr/bin/env python3
"""Run a read-only GitHub Actions inventory audit."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from retention_governance.providers.github_actions import GitHubActionsClient


def main() -> int:
    parser=argparse.ArgumentParser(description='Read-only GitHub Actions inventory; never mutates provider state.')
    parser.add_argument('--owner', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--token-env', default='GITHUB_TOKEN')
    parser.add_argument('--api-version', default='2026-03-10')
    parser.add_argument('--warning-days', type=int, default=30)
    parser.add_argument('--release-roots', type=Path, help='JSON mapping release IDs to root object IDs.')
    parser.add_argument('--include-checks', action='store_true')
    parser.add_argument('--include-statuses', action='store_true')
    args=parser.parse_args()
    release_roots={}
    if args.release_roots:
        release_roots=json.loads(args.release_roots.read_text())
        release_roots={key: tuple(value) for key, value in release_roots.items()}
    token=os.environ.get(args.token_env)
    collection=GitHubActionsClient(token=token, api_version=args.api_version).collect(
        args.owner, args.repo, warning_days=args.warning_days, release_roots=release_roots,
        include_checks=args.include_checks, include_statuses=args.include_statuses
    )
    payload={
        'repository': collection.repository,
        'retention_settings': collection.retention_settings,
        'request_log': list(collection.request_log),
        'snapshot': collection.snapshot.as_dict(),
        'warnings': list(collection.warnings),
        'read_only': True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'output':str(args.output), 'objects':len(collection.snapshot.objects), 'requests':collection.snapshot.api_requests, 'failures':collection.snapshot.failed_requests}, indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
