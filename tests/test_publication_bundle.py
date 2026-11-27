from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

pytest.importorskip("numpy")
pytest.importorskip("torch")

from diffeoforge.cli import main  # noqa: E402
from diffeoforge.modern_workflow import (  # noqa: E402
    load_modern_workflow_config,
    run_modern_workflow,
)
from diffeoforge.publication_bundle import (  # noqa: E402
    PUBLICATION_CAPTIONS,
    PUBLICATION_INDEX,
    PUBLICATION_README,
    PublicationBundleError,
    verify_publication_bundle,
    write_publication_bundle,
)

ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "minimal-modern-atlas.yaml"
FIXED_TIME = "2026-08-30T12:00:00+00:00"


def _run_result(tmp_path: Path) -> Path:
    config = copy.deepcopy(load_modern_workflow_config(EXAMPLE_CONFIG))
    meshes = ROOT / "examples" / "synthetic" / "meshes"
    config["input"]["directory"] = str(meshes)
    config["input"]["template"] = str(meshes / "template.vtk")
    config["optimization"]["max_cycles"] = 1
    config["output"]["directory"] = str(tmp_path / "unused")
    source = tmp_path / "modern.yaml"
    source.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return run_modern_workflow(
        source,
        destination=tmp_path / "modern-result",
        created_at=FIXED_TIME,
    )


def test_publication_bundle_packages_verified_open_artifacts(tmp_path: Path) -> None:
    run = _run_result(tmp_path)

    artifact = write_publication_bundle(
        run,
        tmp_path / "publication",
        created_at=FIXED_TIME,
    )

    verified = verify_publication_bundle(artifact.directory)
    copied = verified.manifest["selection"]["copied_artifacts"]
    roles = {record["role"] for record in copied}
    keys = {record["source_key"] for record in copied}
    assert {"figures", "tables-and-evidence", "meshes"} <= roles
    assert {"estimated-template", "pca-mean-shape", "pc1-minus", "pc1-plus"} <= keys
    assert not (artifact.directory / "reconstructions").exists()
    assert (artifact.directory / "scientific-report" / "scientific-report.html").is_file()
    assert (artifact.directory / PUBLICATION_INDEX).is_file()
    assert (artifact.directory / PUBLICATION_CAPTIONS).is_file()
    readme = (artifact.directory / PUBLICATION_README).read_text(encoding="utf-8")
    assert "not synthesized from endpoint meshes" in readme


def test_publication_bundle_detects_tampering_and_verify_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = write_publication_bundle(
        _run_result(tmp_path),
        tmp_path / "publication",
        created_at=FIXED_TIME,
    )
    assert main(["publication-verify", str(artifact.directory)]) == 0
    assert "Publication bundle verified" in capsys.readouterr().out

    index = artifact.directory / PUBLICATION_INDEX
    index.write_bytes(index.read_bytes() + b"\n")
    with pytest.raises(PublicationBundleError, match="artifact changed"):
        verify_publication_bundle(artifact.directory)
