"""Every tracked n8n workflow is what its generator produces.

The workflows are generated from scripts so the Code-node bodies stay readable,
and a generator that no longer reproduces its file is invisible until someone
runs it: on 2026-09-06 the status API's page cap was raised from 50 to 500 in
the JSON alone, and the generator kept saying 50 until it was run again the next
day. This test runs each generator and compares bytes, so that class of drift
fails here rather than on the NAS.

The generators write their output next to the tracked file; the test restores
the original bytes afterwards, so a failing run leaves the tree as it found it.
"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "n8n" / "build"

GENERATORS = [
    ("build_status_workflow.py", "incident_status_api_v1.json"),
    ("build_transition_workflow.py", "incident_transition_v1.json"),
    ("build_escalation_workflow.py", "escalation_record_v1.json"),
    ("build_overdue_workflow.py", "overdue_escalation_v1.json"),
    ("build_digest_workflow.py", "daily_digest_v1.json"),
    ("build_comparison_slice.py", "comparison_slice_v1.json"),
    ("build_store_sync_workflow.py", "store_sync_v1.json"),
]


@pytest.mark.parametrize("generator, tracked", GENERATORS)
def test_generator_reproduces_its_tracked_workflow(generator, tracked):
    path = ROOT / "n8n" / tracked
    before = path.read_bytes()
    try:
        result = subprocess.run(
            [sys.executable, str(BUILD / generator)], capture_output=True, text=True, cwd=str(BUILD)
        )
        after = path.read_bytes()
    finally:
        path.write_bytes(before)
    assert result.returncode == 0, result.stdout + result.stderr
    assert after == before, "%s no longer reproduces %s" % (generator, tracked)
