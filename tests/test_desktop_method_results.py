import time

import numpy as np
import pytest

pytest.importorskip("PySide6")

from test_reference_pca import _completed_reference_run

from diffeoforge.desktop.method_results import (
    Method3DDialog,
    MethodResultsPanel,
    axis_prefix,
    mesh_glyphs,
    read_method_views,
    saved_method_views,
)
from diffeoforge.desktop.reference_result_review import review_reference_result
from diffeoforge.reference_shape_space_comparison import (
    ALL_METHOD_IDS,
    verify_reference_shape_space_comparison,
    write_reference_shape_space_comparison,
)


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def wait_for(qapp, predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_method_library_preserves_selections_exact_scores_and_source_binding(tmp_path):
    run = _completed_reference_run(tmp_path, three_components=True)
    root = write_reference_shape_space_comparison(run, method_ids=ALL_METHOD_IDS)
    artifact = verify_reference_shape_space_comparison(root)
    labels, methods, scores = read_method_views(artifact, run)
    assert {m["method_id"] for m in methods} == set(ALL_METHOD_IDS)
    second = run / "analysis" / "reference-shape-space-comparison-new-selection"
    write_reference_shape_space_comparison(run, second)
    combined, notices = saved_method_views(run)
    assert not notices
    assert combined[0] == labels
    assert set(combined[2]) == set(ALL_METHOD_IDS)
    for key in scores:
        np.testing.assert_array_equal(combined[2][key], scores[key])
    (run / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="source result changed"):
        read_method_views(artifact, run)


def test_method_views_and_3d_use_verified_specimen_order_without_variance_claim(qapp, tmp_path):
    run = _completed_reference_run(tmp_path, three_components=True)
    artifact = verify_reference_shape_space_comparison(
        write_reference_shape_space_comparison(run, method_ids=ALL_METHOD_IDS)
    )
    review = review_reference_result(run)
    panel = MethodResultsPanel()
    panel.resize(1100, 650)
    panel.load(artifact, review)
    wait_for(qapp, lambda: panel.result is not None)
    assert panel.methods.count() == len(ALL_METHOD_IDS)
    for index in range(panel.methods.count()):
        panel.methods.setCurrentIndex(index)
        key = panel.methods.currentData()
        dimensions = panel.result[2][key].shape[1]
        assert panel.three_d.isEnabled() == (dimensions >= 3)
        assert axis_prefix(key) in panel.x_axis.currentText()
        assert "variance" not in panel.status.text()
        if dimensions < 3:
            continue
        method = next(m for m in panel.result[1] if m["method_id"] == key)
        dialog = Method3DDialog(review, panel.result[0], panel.result[2][key][:, :3], method)
        dialog.show()
        wait_for(qapp, lambda current=dialog: current.viewer.canvas.data is not None)
        np.testing.assert_array_equal(dialog.viewer.canvas.data[0], panel.result[2][key][:, :3])
        assert dialog.viewer.canvas.labels == list(panel.result[0])
        assert dialog.viewer.canvas.data[3] is None
        assert axis_prefix(key) in dialog.viewer.canvas._label(0)
        canvas = dialog.viewer.canvas
        wait_for(qapp, lambda current=canvas: current.cache.ready(current._scene()[0]))
        assert not canvas.snapshot().isNull()
        canvas.yaw += 0.2
        with pytest.raises(ValueError, match="current camera"):
            canvas.snapshot()
        dialog.close()
    panel.clear()
    assert not panel.three_d.isEnabled()
    assert panel.result is None


def test_mismatched_specimens_never_get_filename_guessed(qapp, tmp_path):
    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    with pytest.raises(ValueError, match="specimens differ"):
        Method3DDialog(
            review,
            ("unrelated",),
            np.zeros((1, 3)),
            {"label": "PCA", "method_id": "cartesian_momenta_pca"},
        )


def test_method_axis_names_distinguish_non_pca_embeddings():
    assert axis_prefix("isomap") == "Dim"
    assert axis_prefix("diffusion_map") == "DC"
    assert axis_prefix("lddmm_tangent_pcoa") == "PCo"
    assert axis_prefix("rbf_kpca_gamma_1") == "kPC"
    assert axis_prefix("cartesian_momenta_pca") == "PC"


def test_method_switch_reuses_mesh_geometry_but_rechecks_current_bytes(qapp, tmp_path, monkeypatch):
    import diffeoforge.analysis.pca_media_rendering as rendering

    run = _completed_reference_run(tmp_path)
    review = review_reference_result(run)
    records = []
    for item in review.registration_qc:
        artifact = review.artifact(item.reconstruction_artifact_key)
        records.append((artifact.path, artifact.bytes, artifact.sha256))
    scores = np.zeros((len(records), 3))
    first = mesh_glyphs(records, scores)
    monkeypatch.setattr(rendering, "read_mesh", lambda _: pytest.fail("Geometry was parsed twice"))
    changed_scores = scores + [1.0, 2.0, 3.0]
    second = mesh_glyphs(records, changed_scores)
    np.testing.assert_array_equal(second[0], changed_scores)
    np.testing.assert_array_equal(second[1], first[1])
    path = records[0][0]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed since result verification"):
        mesh_glyphs(records, changed_scores)
