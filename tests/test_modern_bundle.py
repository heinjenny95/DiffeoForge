from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pca_module = pytest.importorskip("diffeoforge.analysis.pca")
engine = pytest.importorskip("diffeoforge.engine")
mesh = pytest.importorskip("diffeoforge.mesh")
bundle_module = pytest.importorskip("diffeoforge.modern_bundle")

momenta_pca = pca_module.momenta_pca
flow_points = engine.flow_points
optimize_atlas = engine.optimize_atlas
shoot = engine.shoot
inspect_vtk = mesh.inspect_vtk
read_vtk_points = mesh.read_vtk_points
sha256_file = mesh.sha256_file
MANIFEST_NAME = bundle_module.MANIFEST_NAME
MANIFEST_SIDECAR_NAME = bundle_module.MANIFEST_SIDECAR_NAME
ModernAtlasModelSettings = bundle_module.ModernAtlasModelSettings
ModernBundleError = bundle_module.ModernBundleError
verify_modern_atlas_bundle = bundle_module.verify_modern_atlas_bundle
write_modern_atlas_bundle = bundle_module.write_modern_atlas_bundle

DTYPE = torch.float64
FIXED_TIME = "2026-07-16T08:00:00+00:00"
REFERENCE_FIXTURE = (
    Path(__file__).parents[1]
    / "reference"
    / "modern-engine-v0.2"
    / "deformetrica-4.3.0-objective.json"
)
LABELS = ("specimen ä", "specimen a", "=formula specimen")


def _problem() -> tuple:
    values = json.loads(REFERENCE_FIXTURE.read_text(encoding="utf-8"))["inputs"]
    template = torch.tensor(values["template_vertices"], dtype=DTYPE)
    target = torch.tensor(values["target_vertices"], dtype=DTYPE)
    triangles = torch.tensor(values["triangles"], dtype=torch.int64)
    control_points = torch.tensor(values["control_points"], dtype=DTYPE)
    translations = (
        torch.tensor([0.0, 0.0, 0.0], dtype=DTYPE),
        torch.tensor([0.01, -0.015, 0.02], dtype=DTYPE),
        torch.tensor([-0.02, 0.01, -0.005], dtype=DTYPE),
    )
    targets = tuple((target + translation, triangles) for translation in translations)
    momenta = torch.zeros((len(targets), *control_points.shape), dtype=DTYPE)
    model = ModernAtlasModelSettings(
        deformation_kernel_width=values["deformation_width"],
        attachment_kernel_width=values["attachment_width"],
        noise_variance=values["noise_variance"],
        number_of_time_points=values["number_of_time_points"],
        attachment_type="current",
        shooting_integrator=values["shooting_integrator"],
        flow_integrator=values["flow_integrator"],
    )
    result = optimize_atlas(
        template,
        triangles,
        targets,
        control_points,
        momenta,
        **model.as_manifest(),
        max_cycles=2,
        gradient_tolerance=0.0,
    )
    return result, triangles, model


@pytest.fixture(scope="module")
def optimized() -> tuple:
    return _problem()


def _write_bundle(path: Path, optimized: tuple) -> Path:
    result, triangles, model = optimized
    return write_modern_atlas_bundle(
        path,
        result,
        triangles,
        LABELS,
        model,
        created_at=FIXED_TIME,
    )


def _csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_bundle_contains_verified_open_outputs_and_exact_subject_identity(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, triangles, model = optimized
    originals = (
        result.template_vertices.clone(),
        result.control_points.clone(),
        result.momenta.clone(),
    )
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    manifest = verify_modern_atlas_bundle(bundle)

    assert manifest["bundle_version"] == "0.1"
    assert manifest["created_at"] == FIXED_TIME
    assert manifest["model"] == model.as_manifest()
    assert manifest["optimizer"]["settings"]["block_order"] == [
        "momenta",
        "template",
        "control_points",
    ]
    assert [subject["label"] for subject in manifest["subjects"]] == list(LABELS)
    paths = [subject["reconstruction_path"] for subject in manifest["subjects"]]
    assert len(paths) == len(set(paths))
    assert all(".." not in path for path in paths)
    assert manifest["pca"]["feature_space"] == "subject_initial_momenta_cartesian"
    assert manifest["pca"]["components"] == 2
    assert manifest["pca"]["plots"]["score_axes"] == ["PC1", "PC2"]
    assert manifest["pca"]["deformations"]["standard_deviations"] == 2.0
    assert len(manifest["artifacts"]) == 19
    for tensor, original in zip(
        (result.template_vertices, result.control_points, result.momenta),
        originals,
        strict=True,
    ):
        assert torch.equal(tensor, original)
    for vtk_path in [manifest["template"]["path"], *paths]:
        metadata = inspect_vtk(bundle / vtk_path)
        assert metadata.points == result.template_vertices.shape[0]
        assert metadata.cells == triangles.shape[0]
    momenta_rows = _csv(bundle / manifest["parameters"]["momenta_path"])
    assert momenta_rows[1][0] == LABELS[0]
    formula_row = 1 + 2 * result.control_points.shape[0]
    assert momenta_rows[formula_row][0] == "'=formula specimen"


def test_reconstructions_equal_direct_engine_endpoints(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, _, model = optimized
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    manifest = verify_modern_atlas_bundle(bundle)

    for subject, momenta in zip(manifest["subjects"], result.momenta, strict=True):
        trajectory = shoot(
            result.control_points,
            momenta,
            model.deformation_kernel_width,
            model.number_of_time_points,
            integrator=model.shooting_integrator,
        )
        expected = flow_points(
            result.template_vertices,
            trajectory,
            model.deformation_kernel_width,
            integrator=model.flow_integrator,
        )[-1]
        observed = torch.tensor(
            read_vtk_points(bundle / subject["reconstruction_path"]),
            dtype=DTYPE,
        )
        torch.testing.assert_close(observed, expected, rtol=0, atol=0)


def test_pca_csv_files_reproduce_in_memory_pca(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, _, _ = optimized
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    manifest = verify_modern_atlas_bundle(bundle)
    expected = momenta_pca(
        np.array(result.momenta.numpy(), dtype=np.float64, copy=True),
        subject_labels=LABELS,
    )

    score_rows = _csv(bundle / manifest["pca"]["scores_path"])
    observed_scores = np.array([row[1:] for row in score_rows[1:]], dtype=np.float64)
    loading_rows = _csv(bundle / manifest["pca"]["loadings_path"])
    observed_components = np.array([row[1:] for row in loading_rows[1:]], dtype=np.float64).T
    mean_rows = _csv(bundle / manifest["pca"]["mean_path"])
    observed_mean = np.array([row[1] for row in mean_rows[1:]], dtype=np.float64)

    np.testing.assert_array_equal(observed_scores, expected.scores)
    np.testing.assert_array_equal(observed_components, expected.components)
    np.testing.assert_array_equal(observed_mean, expected.mean)


def test_pca_deformation_meshes_equal_declared_engine_endpoints(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, _, model = optimized
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    manifest = verify_modern_atlas_bundle(bundle)
    pca = momenta_pca(
        np.array(result.momenta.numpy(), dtype=np.float64, copy=True),
        subject_labels=LABELS,
    )
    deformation = manifest["pca"]["deformations"]
    definition = json.loads((bundle / deformation["definition_path"]).read_text(encoding="utf-8"))
    assert definition == {
        key: value for key, value in deformation.items() if key != "definition_path"
    }

    def endpoint(flat_momenta: object) -> object:
        momenta = torch.tensor(
            np.asarray(flat_momenta).reshape(result.control_points.shape),
            dtype=DTYPE,
        )
        trajectory = shoot(
            result.control_points,
            momenta,
            model.deformation_kernel_width,
            model.number_of_time_points,
            integrator=model.shooting_integrator,
        )
        return flow_points(
            result.template_vertices,
            trajectory,
            model.deformation_kernel_width,
            integrator=model.flow_integrator,
        )[-1]

    observed_mean = torch.tensor(read_vtk_points(bundle / deformation["mean_path"]), dtype=DTYPE)
    torch.testing.assert_close(observed_mean, endpoint(pca.mean), rtol=0, atol=0)
    for record in deformation["components"]:
        index = record["component"] - 1
        displacement = (
            deformation["standard_deviations"]
            * np.sqrt(pca.explained_variance[index])
            * pca.components[index]
        )
        minus = pca.mean - displacement
        plus = pca.mean + displacement
        np.testing.assert_allclose(
            (minus + plus) / 2.0,
            pca.mean,
            rtol=0,
            atol=np.finfo(np.float64).eps,
        )
        observed_minus = torch.tensor(read_vtk_points(bundle / record["minus_path"]), dtype=DTYPE)
        observed_plus = torch.tensor(read_vtk_points(bundle / record["plus_path"]), dtype=DTYPE)
        torch.testing.assert_close(observed_minus, endpoint(minus), rtol=0, atol=0)
        torch.testing.assert_close(observed_plus, endpoint(plus), rtol=0, atol=0)


def test_zero_variance_pc_is_explicitly_skipped(tmp_path: Path, optimized: tuple) -> None:
    result, triangles, model = optimized
    direction = torch.linspace(
        0.001,
        0.001 * result.momenta.numel() / result.momenta.shape[0],
        result.momenta[0].numel(),
        dtype=DTYPE,
    ).reshape_as(result.momenta[0])
    rank_one_momenta = torch.stack((-direction, torch.zeros_like(direction), direction))
    rank_one_result = replace(result, momenta=rank_one_momenta)
    bundle = write_modern_atlas_bundle(
        tmp_path / "rank-one",
        rank_one_result,
        triangles,
        LABELS,
        model,
        pca_components=2,
        pca_deformation_components=2,
        created_at=FIXED_TIME,
    )
    deformation = verify_modern_atlas_bundle(bundle)["pca"]["deformations"]

    assert deformation["requested_components"] == 2
    assert [record["component"] for record in deformation["components"]] == [1]
    assert deformation["skipped_zero_variance_components"] == [2]


def test_invalid_pca_deformation_settings_fail_without_publishing(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, triangles, model = optimized
    with pytest.raises(ValueError, match="greater than zero"):
        write_modern_atlas_bundle(
            tmp_path / "invalid-amplitude",
            result,
            triangles,
            LABELS,
            model,
            pca_deformation_standard_deviations=0.0,
        )
    with pytest.raises(ValueError, match="retained PCA"):
        write_modern_atlas_bundle(
            tmp_path / "too-many-components",
            result,
            triangles,
            LABELS,
            model,
            pca_components=1,
            pca_deformation_components=2,
        )

    assert not (tmp_path / "invalid-amplitude").exists()
    assert not (tmp_path / "too-many-components").exists()


def test_fixed_time_bundles_are_byte_identical(tmp_path: Path, optimized: tuple) -> None:
    first = _write_bundle(tmp_path / "first", optimized)
    second = _write_bundle(tmp_path / "second", optimized)
    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }

    assert first_files == second_files


def test_existing_destination_is_never_overwritten(tmp_path: Path, optimized: tuple) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        _write_bundle(destination, optimized)

    assert sentinel.read_text(encoding="utf-8") == "user data"


@pytest.mark.parametrize("mode", ["tamper", "missing", "extra"])
def test_verifier_rejects_any_file_inventory_change(
    tmp_path: Path,
    optimized: tuple,
    mode: str,
) -> None:
    bundle = _write_bundle(tmp_path / mode, optimized)
    manifest = json.loads((bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
    artifact = bundle / manifest["artifacts"][0]["path"]
    if mode == "tamper":
        artifact.write_bytes(artifact.read_bytes() + b"tampered")
    elif mode == "missing":
        artifact.unlink()
    else:
        (bundle / "unlisted.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(ModernBundleError):
        verify_modern_atlas_bundle(bundle)


def test_verifier_rejects_manifest_path_traversal(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    manifest_path = bundle / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../escape.txt"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (bundle / MANIFEST_SIDECAR_NAME).write_text(
        f"{sha256_file(manifest_path)}  {MANIFEST_NAME}\n",
        encoding="ascii",
    )

    with pytest.raises(ModernBundleError, match="escapes"):
        verify_modern_atlas_bundle(bundle)


def test_partial_failure_leaves_no_destination_or_temporary_directory(
    tmp_path: Path,
    optimized: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import diffeoforge.modern_bundle as module

    def fail(*args, **kwargs):
        raise OSError("injected write failure")

    monkeypatch.setattr(module, "write_vtk_polydata", fail)
    destination = tmp_path / "failed"

    with pytest.raises(OSError, match="injected"):
        _write_bundle(destination, optimized)

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".failed.tmp-*"))


def test_failed_final_verification_leaves_no_destination(
    tmp_path: Path,
    optimized: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise ModernBundleError("injected verification failure")

    monkeypatch.setattr(bundle_module, "verify_modern_atlas_bundle", fail)
    destination = tmp_path / "failed-verification"

    with pytest.raises(ModernBundleError, match="injected"):
        _write_bundle(destination, optimized)

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".failed-verification.tmp-*"))


def test_invalid_labels_and_triangle_dtype_fail_before_writing(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, triangles, model = optimized
    with pytest.raises(ValueError, match="unique"):
        write_modern_atlas_bundle(
            tmp_path / "duplicate",
            result,
            triangles,
            ("same", "same", "third"),
            model,
        )
    with pytest.raises(TypeError, match="int64"):
        write_modern_atlas_bundle(
            tmp_path / "triangles",
            result,
            triangles.to(torch.int32),
            LABELS,
            model,
        )
    assert not (tmp_path / "duplicate").exists()
    assert not (tmp_path / "triangles").exists()


def test_creation_time_requires_timezone_aware_iso8601(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    result, triangles, model = optimized

    with pytest.raises(ValueError, match="timezone"):
        write_modern_atlas_bundle(
            tmp_path / "naive-time",
            result,
            triangles,
            LABELS,
            model,
            created_at="2026-07-16T08:00:00",
        )

    assert not (tmp_path / "naive-time").exists()


def test_manifest_sidecar_detects_manifest_edit(tmp_path: Path, optimized: tuple) -> None:
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    manifest_path = bundle / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = "changed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModernBundleError, match="SHA-256"):
        verify_modern_atlas_bundle(bundle)


def test_manifest_hash_is_plain_sha256_not_a_signature(
    tmp_path: Path,
    optimized: tuple,
) -> None:
    bundle = _write_bundle(tmp_path / "bundle", optimized)
    digest, name = (bundle / MANIFEST_SIDECAR_NAME).read_text(encoding="ascii").split()

    assert name == MANIFEST_NAME
    assert digest == hashlib.sha256((bundle / MANIFEST_NAME).read_bytes()).hexdigest()
    assert verify_modern_atlas_bundle(bundle)["immutability_contract"]["signature"] == (
        "not cryptographically signed"
    )
