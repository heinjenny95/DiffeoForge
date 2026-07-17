from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

import pytest

import diffeoforge.reference_preparation_plan as preparation_plan_module
from diffeoforge.backends import render_engine_file_bytes
from diffeoforge.config import ConfigurationError, load_config
from diffeoforge.reference_preparation_plan import (
    plan_reference_preparation,
    reference_preparation_plan_fingerprint,
    render_reference_preparation_plan_html,
    write_reference_preparation_plan_report,
)
from diffeoforge.runs import prepare_run, verify_prepared_run

ROOT = Path(__file__).parents[1]
WINDOWS_XML_HASHES = {
    "data_set.xml": "67810f68fd34b82302f853bee20353af5ef43a05cc5de19c827cc31758f0cd3f",
    "model.xml": "358d6cdd859e602302ca04f052e68a189800686a9789bf87e403abca7f817b3e",
    "optimization_parameters.xml": (
        "ec96f29b2fefcc678f1ee66aec344dd18f3a4dc017495cf25bf09af4750e76d4"
    ),
}
POSIX_XML_HASHES = {
    "data_set.xml": "6e742561eb0e176996b2b670a288210179b79573935206f7453e8230b6229914",
    "model.xml": "51939375eb5bf43080b066a0334f827a4dee5ed4766c75dc8467844dbd14afe6",
    "optimization_parameters.xml": (
        "4a4599f1e6e00bae5fdc53ee26e893c5cf92c1bc2b6e237f3798686e6a4fa71e"
    ),
}


class _ActiveContentCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.url_attributes: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.append(tag)
        self.url_attributes.extend(
            (name, value or "") for name, value in attrs if name in {"href", "src"}
        )


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Preparation Plan Käfer"
    shutil.copytree(ROOT / "examples" / "synthetic", root / "synthetic")
    shutil.copyfile(ROOT / "examples" / "minimal-atlas-container.yaml", root / "atlas.yaml")
    return root


def _tree_inventory(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_reference_preparation_plan_is_deterministic_and_read_only(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    before = _tree_inventory(root)

    first = plan_reference_preparation(config, run_id="pilot Käfer 001")
    second = plan_reference_preparation(config, run_id="pilot Käfer 001")

    assert first == second
    assert _tree_inventory(root) == before
    assert not (root / "runs").exists()
    assert first["schema_version"] == "0.1"
    assert first["status"] == "read_only_plan_not_prepared"
    assert first["run"]["run_id"] == "pilot-K-fer-001"
    assert first["run"]["destination_exists"] is False
    assert first["input_count"] == {"templates": 1, "subjects": 5}
    assert first["protected_file_count"] == 11
    assert first["protected_file_count"] == len(first["protected_files"])
    assert first["total_protected_bytes"] == sum(
        item["bytes"] for item in first["protected_files"]
    )
    assert [item["path"] for item in first["protected_files"]][-3:] == [
        "engine/model.xml",
        "engine/data_set.xml",
        "engine/optimization_parameters.xml",
    ]
    assert "creates no directory" in first["scientific_boundary"]


def test_reference_preparation_plan_matches_real_preparation_byte_for_byte(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    plan = plan_reference_preparation(config, run_id="parity-001")

    run = prepare_run(config, run_id="parity-001")
    manifest = verify_prepared_run(run)

    assert run == Path(plan["run"]["destination"])
    assert manifest["command_preview"] == plan["command_preview"]
    assert manifest["effective_config"] == plan["effective_config"]
    assert manifest["inputs"] == plan["inputs"]
    assert [item["path"] for item in manifest["protected_artifacts"]] == [
        item["path"] for item in plan["protected_files"]
    ]
    for planned in plan["protected_files"]:
        actual = run / planned["path"]
        payload = actual.read_bytes()
        assert len(payload) == planned["bytes"]
        assert hashlib.sha256(payload).hexdigest() == planned["sha256"]
        if planned["kind"] == "generated":
            assert payload == planned["content_utf8"].encode("utf-8")


def test_pure_xml_renderer_preserves_established_native_bytes() -> None:
    config = load_config(ROOT / "examples" / "minimal-atlas-container.yaml")
    rendered = render_engine_file_bytes(
        config,
        Path("../input/template/template.vtk"),
        [Path(f"../input/subjects/subject-{index:02d}.vtk") for index in range(1, 6)],
    )
    expected = WINDOWS_XML_HASHES if os.name == "nt" else POSIX_XML_HASHES

    assert {name: hashlib.sha256(payload).hexdigest() for name, payload in rendered.items()} == (
        expected
    )


def test_reference_preparation_plan_rejects_existing_destination(tmp_path: Path) -> None:
    root = _project(tmp_path)
    destination = root / "runs" / "reserved"
    destination.mkdir(parents=True)

    with pytest.raises(ConfigurationError, match="already exists"):
        plan_reference_preparation(root / "atlas.yaml", run_id="reserved")


def test_reference_preparation_plan_rejects_inventory_change_during_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path)
    real_inspect = preparation_plan_module.inspect_inputs

    def inspect_then_add_subject(summary):
        result = real_inspect(summary)
        shutil.copyfile(summary.subjects[0], summary.input_directory / "subject-99.vtk")
        return result

    monkeypatch.setattr(preparation_plan_module, "inspect_inputs", inspect_then_add_subject)

    with pytest.raises(ConfigurationError, match="inventory changed"):
        plan_reference_preparation(root / "atlas.yaml", run_id="changing-inputs")


def test_reference_plan_cli_emits_ascii_safe_json_without_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    before = _tree_inventory(root)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan",
            str(config),
            "--run-id",
            "cli Käfer 001",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert all(byte < 128 for byte in completed.stdout)
    plan = json.loads(completed.stdout.decode("ascii"))
    assert plan["run"]["run_id"] == "cli-K-fer-001"
    assert plan["run"]["destination_exists"] is False
    assert _tree_inventory(root) == before
    assert not (root / "runs").exists()


def test_reference_preparation_html_is_deterministic_complete_and_escaped(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="html-review")
    hostile = deepcopy(plan)
    hostile["scientific_boundary"] += ' <script src="https://invalid.example/x.js">&unsafe</script>'

    first = render_reference_preparation_plan_html(hostile)
    second = render_reference_preparation_plan_html(hostile)

    assert first == second
    assert reference_preparation_plan_fingerprint(hostile) in first
    assert "Review only - destination absent - nothing prepared" in first
    assert hostile["source_config"]["sha256"] in first
    assert all(item["geometry"]["sha256"] in first for item in hostile["inputs"])
    assert all(item["sha256"] in first for item in hostile["protected_files"])
    assert all(
        html.escape(item["content_utf8"]) in first
        for item in hostile["protected_files"]
        if item["kind"] == "generated"
    )
    assert (
        "&lt;script src=&quot;https://invalid.example/x.js&quot;&gt;"
        "&amp;unsafe&lt;/script&gt;"
    ) in first
    collector = _ActiveContentCollector()
    collector.feed(first)
    assert not {"script", "link", "iframe", "img", "object", "embed"}.intersection(
        collector.tags
    )
    assert collector.url_attributes == []


def test_reference_preparation_html_report_is_exclusive(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = plan_reference_preparation(root / "atlas.yaml", run_id="write-once")
    report = tmp_path / "nested" / "reference-plan.html"

    written = write_reference_preparation_plan_report(plan, report)
    original = report.read_bytes()

    assert written == report.resolve()
    assert original.decode("utf-8") == render_reference_preparation_plan_html(plan)
    with pytest.raises(ConfigurationError, match="will not be overwritten"):
        write_reference_preparation_plan_report(plan, report)
    assert report.read_bytes() == original


def test_reference_preparation_html_scales_to_305_subject_inventory(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    mesh_directory = root / "synthetic" / "meshes"
    source = mesh_directory / "subject-01.vtk"
    for index in range(6, 306):
        shutil.copyfile(source, mesh_directory / f"subject-{index:03d}.vtk")

    plan = plan_reference_preparation(root / "atlas.yaml", run_id="large-review")
    rendered = render_reference_preparation_plan_html(plan)

    assert plan["input_count"] == {"templates": 1, "subjects": 305}
    assert plan["protected_file_count"] == 311
    assert "Subjects<strong>305</strong>" in rendered
    assert "input/subjects/subject-305.vtk" in rendered
    assert plan["inputs"][-1]["geometry"]["sha256"] in rendered
    assert not (root / "runs").exists()


def test_reference_plan_cli_optionally_writes_html_without_changing_json_stdout(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    config = root / "atlas.yaml"
    report = root / "review" / "reference-plan.html"
    before = _tree_inventory(root)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan",
            str(config),
            "--run-id",
            "report-001",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert all(byte < 128 for byte in completed.stdout)
    plan = json.loads(completed.stdout.decode("ascii"))
    assert plan["run"]["destination_exists"] is False
    assert report.read_bytes().decode("utf-8") == render_reference_preparation_plan_html(plan)
    assert all(byte < 128 for byte in completed.stderr)
    assert completed.stderr.decode("ascii").strip() == (
        "Reference preparation report: "
        f"{json.dumps(str(report.resolve()), ensure_ascii=True)}"
    )
    after = _tree_inventory(root)
    assert set(after) - set(before) == {"review/reference-plan.html"}
    assert not (root / "runs").exists()


def test_reference_plan_cli_refuses_existing_report_before_emitting_json(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    report = root / "owned.html"
    report.write_text("user content\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "diffeoforge",
            "reference-plan",
            str(root / "atlas.yaml"),
            "--run-id",
            "blocked-report",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "will not be overwritten" in completed.stderr
    assert report.read_text(encoding="utf-8") == "user content\n"
