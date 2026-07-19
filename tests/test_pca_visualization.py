from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
analysis = pytest.importorskip("diffeoforge.analysis")

principal_component_analysis = analysis.principal_component_analysis
write_pca_scores_svg = analysis.write_pca_scores_svg
write_pca_score_pair_svg = analysis.write_pca_score_pair_svg
write_pca_scree_svg = analysis.write_pca_scree_svg

SVG = "{http://www.w3.org/2000/svg}"


def _pca(*, components: int) -> object:
    features = np.array(
        [
            [-2.0, -2.0],
            [-1.0, -1.0],
            [1.0, 1.0],
            [2.0, 2.0],
        ],
        dtype=np.float64,
    )
    return principal_component_analysis(
        features,
        n_components=components,
        feature_space="rank_one_test",
        sample_labels=("plain", "A&B", "<specimen>", 'quote " specimen'),
    )


def test_svg_plots_are_valid_static_escaped_and_byte_repeatable(tmp_path: Path) -> None:
    pca = _pca(components=2)
    first_scree = write_pca_scree_svg(tmp_path / "first-scree.svg", pca)
    second_scree = write_pca_scree_svg(tmp_path / "second-scree.svg", pca)
    first_scores = write_pca_scores_svg(tmp_path / "first-scores.svg", pca)
    second_scores = write_pca_scores_svg(tmp_path / "second-scores.svg", pca)

    assert first_scree.read_bytes() == second_scree.read_bytes()
    assert first_scores.read_bytes() == second_scores.read_bytes()
    assert b"font-family: Arial" in first_scree.read_bytes()
    assert b"font-family: Arial" in first_scores.read_bytes()
    for path in (first_scree, first_scores):
        root = ET.parse(path).getroot()
        assert root.tag == f"{SVG}svg"
        assert not root.findall(f".//{SVG}script")
        assert all(
            attribute.rsplit("}", 1)[-1] != "href"
            for element in root.iter()
            for attribute in element.attrib
        )
    titles = [element.text for element in ET.parse(first_scores).iter(f"{SVG}title")]
    assert "A&B" in titles
    assert "<specimen>" in titles
    assert 'quote " specimen' in titles


def test_one_component_pca_is_an_explicit_pc1_strip(tmp_path: Path) -> None:
    path = write_pca_scores_svg(tmp_path / "strip.svg", _pca(components=1))
    text = path.read_text(encoding="utf-8")

    assert "PC1 strip" in text
    assert "no PC2 retained" in text
    assert "PC1 vs PC2" not in text


def test_declared_pc2_pc3_plot_has_exact_axes_subject_order_and_variance_labels(
    tmp_path: Path,
) -> None:
    pca = principal_component_analysis(
        np.array(
            [
                [-2.0, -1.0, 0.0],
                [-1.0, 2.0, 1.0],
                [0.5, -0.5, 3.0],
                [1.0, 1.5, -2.0],
                [2.5, -2.0, -1.0],
            ],
            dtype=np.float64,
        ),
        n_components=3,
        feature_space="three_component_test",
        sample_labels=("one", "two", "three", "four", "five"),
    )

    path = write_pca_score_pair_svg(
        tmp_path / "pc2-pc3.svg",
        pca,
        x_component=2,
        y_component=3,
    )
    text = path.read_text(encoding="utf-8")
    root = ET.parse(path).getroot()

    assert "PCA subject scores: PC2 vs PC3" in text
    assert f"PC2 ({pca.explained_variance_ratio[1] * 100:.2f}%)" in text
    assert f"PC3 ({pca.explained_variance_ratio[2] * 100:.2f}%)" in text
    assert [circle.attrib["data-subject-label"] for circle in root.findall(f".//{SVG}circle")] == [
        "one",
        "two",
        "three",
        "four",
        "five",
    ]


def test_score_plot_tick_labels_are_compact_for_embedded_desktop_rendering(
    tmp_path: Path,
) -> None:
    path = write_pca_scores_svg(tmp_path / "scores.svg", _pca(components=2))
    root = ET.parse(path).getroot()
    tick_labels = [
        element.text or ""
        for element in root.findall(f".//{SVG}text")
        if element.attrib.get("class") == "small"
    ]

    assert len(tick_labels) == 12
    assert all(len(label) <= 9 for label in tick_labels)
    assert all(label.count(".") <= 1 for label in tick_labels)


def test_score_pair_rejects_missing_or_repeated_components(tmp_path: Path) -> None:
    pca = _pca(components=2)

    with pytest.raises(ValueError, match="between 1 and 2"):
        write_pca_score_pair_svg(
            tmp_path / "missing.svg",
            pca,
            x_component=2,
            y_component=3,
        )
    with pytest.raises(ValueError, match="must differ"):
        write_pca_score_pair_svg(
            tmp_path / "repeated.svg",
            pca,
            x_component=1,
            y_component=1,
        )


def test_plot_writer_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "existing.svg"
    path.write_text("user data", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_pca_scree_svg(path, _pca(components=1))

    assert path.read_text(encoding="utf-8") == "user data"
