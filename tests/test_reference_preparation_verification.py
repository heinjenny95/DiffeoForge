from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import diffeoforge.reference_preparation_verification as verification_module
from diffeoforge.config import ConfigurationError
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
    write_reference_preparation_plan_report,
)
from diffeoforge.reference_preparation_verification import (
    serialize_reference_preparation_plan_verification,
    verify_saved_reference_preparation_plan,
    write_reference_preparation_plan_verification,
)

ROOT = Path(__file__).parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Saved Plan Verification Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _save_plan(plan: dict, destination: Path) -> None:
    destination.write_text(
        json.dumps(plan, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )


def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_verify_saved_plan_and_html_is_deterministic_and_read_only(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="verified-review")
    saved_plan = root / "review" / "plan.json"
    saved_plan.parent.mkdir()
    _save_plan(plan, saved_plan)
    report = write_reference_preparation_plan_report(plan, root / "review" / "plan.html")
    fingerprint = reference_preparation_plan_fingerprint(plan)
    before = _inventory(root)

    first = verify_saved_reference_preparation_plan(
        saved_plan,
        report_path=report,
        expected_fingerprint=fingerprint.upper(),
    )
    second = verify_saved_reference_preparation_plan(
        saved_plan,
        report_path=report,
        expected_fingerprint=fingerprint,
    )

    assert first == second
    assert _inventory(root) == before
    assert first["schema_version"] == "0.1"
    assert first["status"] == "verified_saved_reference_preparation_plan"
    assert first["plan"]["canonical_fingerprint"] == fingerprint
    assert first["plan"]["expected_fingerprint"] == fingerprint
    assert first["report"]["matches_deterministic_regeneration"] is True
    assert first["recorded_plan"]["subjects"] == 5
    assert "does not prove that source config or mesh files still match" in first[
        "scientific_boundary"
    ]


def test_verify_saved_plan_without_report_records_limited_scope(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="plan-only")
    saved_plan = root / "plan-only.json"
    _save_plan(plan, saved_plan)

    evidence = verify_saved_reference_preparation_plan(saved_plan)

    assert evidence["report"] is None
    assert evidence["plan"]["expected_fingerprint"] is None
    assert "report_exact_deterministic_regeneration" not in evidence["checks"]
    assert "plan_fingerprint_matches_expected" not in evidence["checks"]


def test_plan_verification_evidence_write_is_exact_exclusive_and_requires_parent(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="evidence-file")
    saved_plan = root / "plan.json"
    _save_plan(plan, saved_plan)
    evidence = verify_saved_reference_preparation_plan(saved_plan)
    payload = serialize_reference_preparation_plan_verification(evidence)
    output = root / "evidence" / "plan-verification.json"
    output.parent.mkdir()

    written = write_reference_preparation_plan_verification(evidence, output)

    assert written == output.resolve()
    assert written.read_bytes() == payload
    assert all(byte < 128 for byte in payload)
    invalid = json.loads(json.dumps(evidence))
    invalid["status"] = "unverified"
    with pytest.raises(ConfigurationError, match="schema violation"):
        serialize_reference_preparation_plan_verification(invalid)
    preserved = written.read_bytes()
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_reference_preparation_plan_verification(evidence, output)
    assert written.read_bytes() == preserved
    with pytest.raises(ConfigurationError, match="existing real directory"):
        write_reference_preparation_plan_verification(
            evidence,
            root / "missing" / "plan-verification.json",
        )
    assert not (root / "missing").exists()


def test_verify_rejects_duplicate_keys_trailing_data_and_nonfinite_constants(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="strict-json")
    encoded = json.dumps(plan, ensure_ascii=True, sort_keys=True)
    saved_plan = root / "strict.json"

    saved_plan.write_text(
        '{"schema_version":"0.1",' + encoded.lstrip()[1:],
        encoding="ascii",
    )
    with pytest.raises(ConfigurationError, match="duplicate JSON object key"):
        verify_saved_reference_preparation_plan(saved_plan)

    saved_plan.write_text(encoded + "\n{}\n", encoding="ascii")
    with pytest.raises(ConfigurationError, match="not one valid JSON document"):
        verify_saved_reference_preparation_plan(saved_plan)

    saved_plan.write_text('{"value": NaN}\n', encoding="ascii")
    with pytest.raises(ConfigurationError, match="unsupported JSON constant"):
        verify_saved_reference_preparation_plan(saved_plan)


def test_verify_rejects_fingerprint_or_html_tampering_without_repair(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="tamper-check")
    saved_plan = root / "plan.json"
    _save_plan(plan, saved_plan)
    report = write_reference_preparation_plan_report(plan, root / "plan.html")

    with pytest.raises(ConfigurationError, match="canonical fingerprint mismatch"):
        verify_saved_reference_preparation_plan(
            saved_plan,
            expected_fingerprint="0" * 64,
        )

    report.write_bytes(report.read_bytes() + b"\n<!-- changed -->\n")
    tampered = report.read_bytes()
    with pytest.raises(ConfigurationError, match="does not exactly match"):
        verify_saved_reference_preparation_plan(saved_plan, report_path=report)
    assert report.read_bytes() == tampered


def test_verify_detects_plan_race_after_valid_report_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="race-check")
    saved_plan = root / "plan.json"
    _save_plan(plan, saved_plan)
    report = write_reference_preparation_plan_report(plan, root / "plan.html")
    original_render = verification_module.render_reference_preparation_plan_html

    def render_then_change(value):
        rendered = original_render(value)
        saved_plan.write_bytes(saved_plan.read_bytes() + b" ")
        return rendered

    monkeypatch.setattr(
        verification_module,
        "render_reference_preparation_plan_html",
        render_then_change,
    )

    with pytest.raises(ConfigurationError, match="changed during verification"):
        verify_saved_reference_preparation_plan(saved_plan, report_path=report)


def test_reference_plan_verify_cli_is_ascii_safe_in_unicode_paths(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="cli-verify")
    saved_plan = root / "Überprüfung" / "plan.json"
    saved_plan.parent.mkdir()
    _save_plan(plan, saved_plan)
    report = write_reference_preparation_plan_report(plan, saved_plan.with_suffix(".html"))
    before = _inventory(root)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan-verify",
            str(saved_plan),
            "--report",
            str(report),
            "--expect-fingerprint",
            reference_preparation_plan_fingerprint(plan),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    assert all(byte < 128 for byte in completed.stdout)
    evidence = json.loads(completed.stdout.decode("ascii"))
    assert completed.stdout == serialize_reference_preparation_plan_verification(evidence)
    assert evidence["report"]["matches_deterministic_regeneration"] is True
    assert evidence["recorded_plan"]["run_id"] == "cli-verify"
    assert _inventory(root) == before

    output = root / "Überprüfung" / "plan-verification.json"
    exported = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan-verify",
            str(saved_plan),
            "--report",
            str(report),
            "--expect-fingerprint",
            reference_preparation_plan_fingerprint(plan),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert exported.returncode == 0, exported.stderr.decode(errors="replace")
    assert exported.stderr == b""
    assert output.read_bytes() == completed.stdout
    output_text = exported.stdout.decode("ascii")
    assert (
        "Saved plan verification evidence: "
        f"{json.dumps(str(output.resolve()), ensure_ascii=True)}" in output_text
    )
    assert hashlib.sha256(completed.stdout).hexdigest() in output_text
    preserved = output.read_bytes()
    duplicate = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan-verify",
            str(saved_plan),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    assert duplicate.returncode == 2
    assert b"will not be overwritten" in duplicate.stderr
    assert output.read_bytes() == preserved
