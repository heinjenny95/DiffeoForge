"""Local improvement accounts for both missed and unsupported surfaces."""
import pytest

from diffeoforge.regional_quality import _local_improved


def rows(forward, reverse):
    return [dict(original_to_fit_mean=forward, fit_to_original_mean=reverse)]*2


def test_removing_an_extra_projection_can_improve_the_symmetric_surface_measure():
    assert _local_improved(rows(.012, .02), rows(.01, .08))


def test_forward_improvement_cannot_hide_a_worse_unsupported_projection():
    assert not _local_improved(rows(.02, .09), rows(.08, .01))


@pytest.mark.parametrize('current,before', [
    (rows(.01, .01), None),
    (rows(.01, .077), rows(.01, .08)),
    (rows(.02, .02)+rows(.04, .04), rows(.03, .03)+rows(.1, .1)),
])
def test_improvement_requires_a_baseline_and_conservative_repeat_agreement(current, before):
    assert not _local_improved(current, before)
