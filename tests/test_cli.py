import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_benchmark_cli_writes_machine_readable_report(tmp_path):
    output=tmp_path/'report.json'
    subprocess.run([sys.executable, str(ROOT/'scripts/run_benchmark.py'), '--output', str(output)], check=True, cwd=ROOT)
    report=json.loads(output.read_text())
    assert report['case_count'] == 5
    assert report['cases'][0]['strategies']['dependency_aware']['plan']['planner_version'] == '0.1.0'
