#!/usr/bin/env python3
"""Run the synthetic retention-governance benchmark."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from retention_governance.benchmark import evaluate_benchmark

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenarios', type=Path, default=ROOT/'scenarios/pilot.json')
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    report=evaluate_benchmark(args.scenarios)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'benchmark_hash': report['benchmark_hash'], 'case_count': report['case_count'], 'output': str(args.output)}, indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
