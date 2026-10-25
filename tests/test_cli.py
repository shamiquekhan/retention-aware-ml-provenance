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


def test_provider_clis_reject_horizonless_release_requests(tmp_path):
    (tmp_path / 'roots.json').write_text('{"release": ["root"]}')
    github = subprocess.run(
        [
            sys.executable,
            str(ROOT / 'scripts/audit_github_actions.py'),
            '--owner', 'acme', '--repo', 'demo',
            '--release-roots', str(tmp_path / 'roots.json'),
            '--output', str(tmp_path / 'github.json'),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert github.returncode != 0
    assert 'audit_horizon' in github.stderr

    ghcr = subprocess.run(
        [
            sys.executable,
            str(ROOT / 'scripts/audit_ghcr.py'),
            '--owner', 'acme', '--package', 'model', '--reference', 'latest',
            '--release-id', 'release', '--output', str(tmp_path / 'ghcr.json'),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ghcr.returncode != 0
    assert 'audit_horizon' in ghcr.stderr
