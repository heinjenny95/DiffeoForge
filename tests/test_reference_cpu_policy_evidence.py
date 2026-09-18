"""Recheck downloaded normal-launch evidence without rerunning an atlas."""

import hashlib
import json
from pathlib import Path

from diffeoforge.reference import compare_reference_run


def test_retained_default_cpu_launches_match_reference_and_recorded_policy():
    root = Path(__file__).parents[1]
    retained = root / "reference/reference-cpu-policy-v1"
    inventory = json.loads((retained / "evidence-sha256.json").read_text())
    assert inventory["source_commit"] == "ab80b503d092d14d41bd2f7790a0e753a41f2944"
    assert inventory["ci_run"] == 34837396916
    assert len(inventory["files"]) == 36
    assert set(inventory["files"]) == {
        p.relative_to(retained).as_posix()
        for p in retained.rglob("*")
        if p.is_file() and p.name not in {"README.md", "evidence-sha256.json"}
    }
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    for name, expected in inventory["files"].items():
        assert sha(retained / name) == expected
    engines = []
    for runner, cpu in (
        ("ubuntu-22.04", "INTEL(R) XEON(R) PLATINUM 8573C"),
        ("ubuntu-24.04", "AMD EPYC 7763 64-Core Processor"),
    ):
        run = retained / runner
        manifest = json.loads((run / "manifest.json").read_text())
        result = json.loads((run / "result.json").read_text())
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        started = next(e for e in events if e["event"] == "started")
        assert sha(run / "manifest.json") == (run / "manifest.sha256").read_text().split()[0]
        assert manifest["backend"]["contract_version"] == "0.3"
        assert manifest["command_preview"] == started["command"] == result["command"]
        command = result["command"]
        assert command["environment"]["MKL_CBWR"] == "COMPATIBLE"
        assert command["argv"].count("MKL_CBWR=COMPATIBLE") == 1
        assert "MKL_CBWR=AUTO" not in command["argv"]
        assert result["status"] == events[-1]["event"] == "completed"
        assert result["return_code"] == 0
        receipt = result["backend_environment"]
        assert receipt == started["backend_environment"]
        assert receipt["cpu_model"] == cpu
        assert receipt["probe_status"] == "verified"
        assert receipt["packages"]["torch"] == "1.6.0+cpu"
        assert receipt["probe_numerical_environment"] == {
            "MKL_CBWR": "COMPATIBLE",
            "OMP_NUM_THREADS": "4",
            "MKL_DEBUG_CPU_TYPE": None,
            "MKL_ENABLE_INSTRUCTIONS": None,
            "MKL_NUM_THREADS": None,
        }
        engine = {
            a["path"]: a["sha256"]
            for a in manifest["protected_artifacts"]
            if a["path"].startswith("engine/")
        }
        assert len(engine) == 3
        assert all(sha(run / name) == expected for name, expected in engine.items())
        engines.append(engine)
        comparison = compare_reference_run(run, root / "reference/synthetic-v1")
        assert comparison["status"] == "passed" and comparison["passed_count"] == 10
        assert all(a["byte_identical"] for a in comparison["artifacts"])
        assert all(
            a["tolerances"] == {"max_absolute": 1e-6, "rms": 1e-7} for a in comparison["artifacts"]
        )
    assert engines[0] == engines[1]
