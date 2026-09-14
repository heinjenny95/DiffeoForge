from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from diffeoforge.backends.deformetrica_reference import CommandSpec

ROOT = Path(__file__).parents[1]


@pytest.fixture
def pair(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        "cpu_pair", ROOT / "tools/observe_reference_cpu_pair.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_config_and_reference_guard(pair, tmp_path):
    assert len(pair.checked_reference(ROOT)["artifacts"]) == 10
    shutil.copytree(ROOT / "examples", tmp_path / "examples", ignore=shutil.ignore_patterns("runs"))
    shutil.copytree(ROOT / "reference/synthetic-v1", tmp_path / "reference/synthetic-v1")
    with (tmp_path / "examples/minimal-atlas-container.yaml").open("a") as stream:
        stream.write("\n# changed\n")
    with pytest.raises(ValueError, match="frozen public"):
        pair.checked_reference(tmp_path)


def test_paired_command_only_adds_explicit_mode_and_cleanup_name(pair):
    original = CommandSpec(
        (
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--network=none",
            pair.IMAGE,
            "estimate",
            "model.xml",
        ),
        "/work",
        {},
    )
    for mode in ("AUTO", "COMPATIBLE"):
        result = pair.paired_command(original, mode, "df-cpu-pair-abc")
        assert result[:6] == [
            "docker",
            "run",
            "--name",
            "df-cpu-pair-abc",
            "--env",
            f"MKL_CBWR={mode}",
        ]
        assert result[6:] == list(original.argv[2:])
    with pytest.raises(ValueError):
        pair.paired_command(original, "AVX2", "df-cpu-pair-abc")
    with pytest.raises(ValueError):
        pair.paired_command(original, "AUTO", "user-container")


def test_prepared_inputs_and_pristine_output_have_separate_postrun_checks(pair, tmp_path):
    run = pair.prepare_run(
        ROOT / "examples/minimal-atlas-container.yaml",
        output_directory=tmp_path,
        run_id="test-pair",
    )
    manifest = pair.verify_prepared_run(run)
    # Real engine logs make a prepared run intentionally non-pristine. The
    # diagnostic must check protected bytes, not rerun pristine-output validation.
    (run / "logs/deformetrica.log").write_text("diagnostic execution\n")
    with pytest.raises(Exception, match="Execution artifact already exists"):
        pair.verify_prepared_run(run)
    assert all(pair.sha(run / a["path"]) == a["sha256"] for a in manifest["protected_artifacts"])


def test_summary_preserves_auto_failures_and_requires_complete_repeats(pair):
    records = [
        {
            "mode": mode,
            "repeat": repeat,
            "engine_sha256": {"model": "same"},
            "artifact_sha256": {"value": mode},
            "comparison": {"status": "passed" if mode == "COMPATIBLE" else "failed"},
        }
        for mode, repeat in pair.ORDER
    ]
    summary = pair.summarize(records)
    assert summary["diagnostic_complete"] and summary["compatible_reference_pass"]
    assert not summary["auto_reference_pass"]
    assert all(summary["mode_repeatability"].values())
    records[-1]["artifact_sha256"] = {"value": "changed"}
    assert not pair.summarize(records)["mode_repeatability"]["AUTO"]
    records[-1]["engine_sha256"] = {"model": "changed"}
    with pytest.raises(ValueError, match="XML differs"):
        pair.summarize(records)
    with pytest.raises(ValueError, match="four"):
        pair.summarize(records[:3])


def test_report_write_never_overwrites_existing_sidecar(pair, tmp_path):
    path = tmp_path / "report.json"
    path.with_suffix(".sha256").write_text("old")
    with pytest.raises(FileExistsError):
        pair.write_json(path, {})
    assert not path.exists()


def test_verifier_rejects_changed_report_before_parsing(pair, tmp_path):
    pair.write_json(tmp_path / "report.json", {"protocol": pair.PROTOCOL})
    with (tmp_path / "report.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        pair.verify(ROOT, tmp_path)


def test_dispatch_is_explicit_and_default_strict_gate_remains(pair):
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/reference-container.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["build-run-compare"]["if"] == "${{ !inputs.cpu_pair }}"
    assert "github.event_name == 'workflow_dispatch'" in jobs["cpu-pair-diagnostic"]["if"]
    assert jobs["cpu-pair-diagnostic"]["strategy"]["fail-fast"] is False
    assert "continue-on-error" not in json.dumps(workflow)


def test_whole_harness_with_fake_containers_and_retained_output_reverification(
    pair, tmp_path, monkeypatch
):
    monkeypatch.setattr(pair.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pair.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(pair.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(pair.os, "getgid", lambda: 1000, raising=False)
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if str(path).replace("\\", "/") == "/proc/cpuinfo":
            return "vendor_id: GenuineIntel\nmodel name: unit-test CPU\n"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(
        pair.subprocess,
        "check_output",
        lambda argv, **kwargs: (
            json.dumps([{"Config": {"Env": []}, "Id": "test-image"}])
            if argv[0] == "docker"
            else "test-source"
        ),
    )
    reference = pair.checked_reference(ROOT)
    calls = []

    def fake_container(argv, log, name):
        calls.append(argv)
        if "estimate" in argv:
            mount = next(value for value in argv if value.endswith("target=/work"))
            run = Path(mount.split("source=", 1)[1].rsplit(",target=", 1)[0])
            for item in reference["artifacts"]:
                if item["run_path"] == "logs/convergence.csv":
                    continue
                destination = run / item["run_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / "reference/synthetic-v1" / item["fixture_path"], destination)
            source_log = next(
                (ROOT / "reference/reference-cpu-audit-v1/ci-amd-34829353422").rglob(
                    "deformetrica.log"
                )
            )
            shutil.copyfile(source_log, log)
        else:
            mode = next(value for value in argv if value.startswith("MKL_CBWR=")).split("=")[1]
            path = tmp_path / "capture/evidence" / f"probe-{mode}.json"
            path.write_text(
                json.dumps(
                    {
                        "cpu_model": "unit-test CPU",
                        "torch": "1.6.0+cpu",
                        "threads": 4,
                        "environment": {"MKL_CBWR": mode},
                    }
                )
            )
            log.write_text("test-only probe\n")

    monkeypatch.setattr(pair, "run_container", fake_container)
    report = pair.observe(ROOT, tmp_path / "capture")
    assert len(calls) == 6
    assert report["diagnostic_complete"]
    assert report["compatible_reference_pass"] and report["auto_reference_pass"]
    assert pair.verify(ROOT, tmp_path / "capture/evidence") == report
    assert not list((tmp_path / "capture/evidence").rglob("*.p"))
    with pytest.raises(FileExistsError):
        pair.observe(ROOT, tmp_path / "capture")
    evidence = tmp_path / "capture/evidence/auto-r1/engine/model.xml"
    with evidence.open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="checksum"):
        pair.verify(ROOT, tmp_path / "capture/evidence")


def test_retained_native_intel_and_amd_full_atlases_rederive_without_threshold_changes(pair):
    retained = ROOT / "reference/reference-cpu-full-pair-v1"
    intel = pair.verify(ROOT, retained / "intel-xeon-8573c")
    amd = pair.verify(ROOT, retained / "amd-epyc-7763")
    assert {intel["cpu_vendor"], amd["cpu_vendor"]} == {"GenuineIntel", "AuthenticAMD"}
    assert (
        intel["source_commit"]
        == amd["source_commit"]
        == ("6113400c29f73a11b81a62ead80b2da1d5efbe2b")
    )
    assert intel["worker_sha256"] == amd["worker_sha256"]
    assert intel["records"][0]["engine_sha256"] == amd["records"][0]["engine_sha256"]
    assert not intel["auto_reference_pass"]
    assert amd["auto_reference_pass"]
    for report in (intel, amd):
        assert report["compatible_reference_pass"]
        assert all(report["mode_repeatability"].values())
        for record in report["records"]:
            expected = 8 if report is intel and record["mode"] == "AUTO" else 10
            assert record["comparison"]["passed_count"] == expected
            assert sum(a["byte_identical"] for a in record["comparison"]["artifacts"]) == expected
            assert all(
                a["tolerances"] == {"max_absolute": 1e-6, "rms": 1e-7}
                for a in record["comparison"]["artifacts"]
            )
    assert intel["records"][1]["artifact_sha256"] == amd["records"][1]["artifact_sha256"]
    probes = [
        json.loads((retained / host / "probe-COMPATIBLE.json").read_text())
        for host in ("intel-xeon-8573c", "amd-epyc-7763")
    ]
    assert probes[0]["threads"] == probes[1]["threads"] == 4
    assert probes[0]["subjects"] == probes[1]["subjects"]
