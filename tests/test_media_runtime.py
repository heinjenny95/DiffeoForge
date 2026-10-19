from __future__ import annotations

import importlib.metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge.media_runtime import verify_media_runtime


def test_media_runtime_encodes_and_decodes_all_synthetic_frames(tmp_path, monkeypatch):
    pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    verify_media_runtime()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("missing", ["imageio", "imageio-ffmpeg"])
def test_missing_metadata_fails_before_encoding(tmp_path, monkeypatch, missing):
    observed = []

    def version(name):
        observed.append(name)
        if name == missing:
            raise importlib.metadata.PackageNotFoundError(name)
        return "test"

    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    with pytest.raises(RuntimeError, match=f"metadata for {missing}"):
        verify_media_runtime()
    assert observed[-1] == missing
    assert not list(tmp_path.iterdir())


def test_frozen_media_smoke_is_part_of_the_build_gate():
    root = Path(__file__).parents[1]
    spec = (root / "distribution/windows/DiffeoForge.spec").read_text()
    build = (root / "distribution/windows/build-evidence.ps1").read_text()
    assert 'copy_metadata("imageio")' in spec
    assert 'copy_metadata("imageio-ffmpeg")' in spec
    assert "datas=schema_data + third_party_data + media_metadata" in spec
    assert '-ArgumentList "--smoke-media"' in build
    assert 'if ($mediaProcess.ExitCode -ne 0)' in build
    assert '"backends": ["QtAgg", "Agg", "PDF", "SVG"]' in spec
    assert spec.count("hooksconfig=matplotlib_hooks") == 5


@pytest.mark.parametrize("missing_backend", ["pdf", "svg"])
def test_missing_file_backend_fails_before_video_or_native_work(
    tmp_path, monkeypatch, missing_backend,
):
    import importlib

    from matplotlib import backend_bases

    module = f"matplotlib.backends.backend_{missing_backend}"
    original = importlib.import_module

    def load(name, package=None):
        if name == module:
            raise ModuleNotFoundError(module)
        return original(name, package)

    # Earlier positive checks cache canvas classes; recreate a fresh process's
    # deferred import so this exercises the missing frozen-module failure.
    monkeypatch.setitem(backend_bases._default_backends, missing_backend, module)
    monkeypatch.setattr(importlib, "import_module", load)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    with pytest.raises(RuntimeError, match=f"Media {missing_backend.upper()} export failed"):
        verify_media_runtime()
    assert not list(tmp_path.iterdir())


def test_media_smoke_returns_failure_without_opening_a_window(monkeypatch, capsys):
    from diffeoforge import media_runtime
    from diffeoforge.desktop.app import main

    def fail():
        raise ModuleNotFoundError("matplotlib.backends.backend_pdf")

    monkeypatch.setattr(media_runtime, "verify_media_runtime", fail)
    assert main(["--smoke-media"]) == 1
    assert "backend_pdf" in capsys.readouterr().err


@pytest.mark.parametrize("cancel", [False, True])
def test_worker_runtime_failure_or_cancellation_precedes_native_work(tmp_path, monkeypatch, cancel):
    pytest.importorskip("PySide6")
    from diffeoforge import media_runtime
    from diffeoforge.desktop import widgets

    worker = widgets._ReferencePCADeformationWorker(tmp_path)
    failures, touched = [], []
    worker.signals.failed.connect(failures.append)

    def runtime():
        if cancel:
            worker.request_cancel()
        else:
            raise RuntimeError("Synthetic missing imageio metadata")

    monkeypatch.setattr(media_runtime, "verify_media_runtime", runtime)
    monkeypatch.setattr(
        widgets, "verify_reference_pca_bundle", lambda *a, **k: touched.append(True)
    )
    worker.run()
    assert len(failures) == 1
    assert ("cancelled" if cancel else "missing imageio") in failures[0]
    assert touched == []
    assert not list(tmp_path.iterdir())


def test_retry_reuses_existing_native_endpoints(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from diffeoforge import media_runtime, pca_media
    from diffeoforge.desktop import widgets

    run = tmp_path / "run"
    (run / "analysis" / widgets.DEFAULT_REFERENCE_PCA_DEFORMATION_DESIGN_DIRECTORY).mkdir(
        parents=True
    )
    (run / widgets.DEFAULT_REFERENCE_PCA_DEFORMATION_RESULT_DIRECTORY).mkdir(parents=True)
    monkeypatch.setattr(media_runtime, "verify_media_runtime", lambda: None)
    monkeypatch.setattr(
        widgets, "verify_reference_pca_bundle",
        lambda *a, **k: SimpleNamespace(pca=SimpleNamespace(number_of_components=3)),
    )
    monkeypatch.setattr(widgets, "verify_reference_pca_deformation_design", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "verify_reference_pca_deformation_result", lambda *a, **k: None)
    monkeypatch.setattr(
        widgets, "execute_reference_pca_deformation_design",
        lambda *a, **k: pytest.fail("Retry must not repeat existing native Shooting"),
    )
    media = tmp_path / "media"
    monkeypatch.setattr(pca_media, "prepare_reference_media", lambda *a, **k: media)
    succeeded, failed = [], []
    worker = widgets._ReferencePCADeformationWorker(run)
    worker.signals.succeeded.connect(succeeded.append)
    worker.signals.failed.connect(failed.append)
    worker.run()
    assert failed == []
    assert succeeded == [media]
