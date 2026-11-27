from types import SimpleNamespace

import pytest

from diffeoforge.desktop.common_review_metrics import sampled_fit_label


def candidate(row, scope="full_targets"):
    return SimpleNamespace(metrics=dict(fit_scope=scope, original_surface_fit={"form": row}))


def test_surface_tails_use_saved_original_diagonal_and_percentiles():
    result = sampled_fit_label(candidate(dict(p95=.04, p99=.16, diagonal=2)), "form")
    assert "P95 2.00%" in result and "P99 8.00%" in result
    assert "original diagonal" in result


@pytest.mark.parametrize("row", [{}, {"diagonal": 0, "p95": .1, "p99": .2},
                                  {"diagonal": 1, "p95": .1, "p99": float("nan")}])
def test_unmeasured_or_invalid_distances_are_omitted(row):
    assert not sampled_fit_label(candidate(row), "form")


def test_other_specimens_proxies_and_residuals_cannot_substitute_for_measured_tails():
    row = dict(diagonal=1, p95=.1, p99=.3)
    assert not sampled_fit_label(candidate(row), "another form")
    assert not sampled_fit_label(candidate(row, scope="screen"), "form")
    assert not sampled_fit_label(SimpleNamespace(metrics=dict(residual_p95=.01)), "form")
