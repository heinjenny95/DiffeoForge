"""New common-fit annotations must inform the same-area trend comparison."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from diffeoforge import pilot_common_diagnosis as diagnosis


@pytest.mark.parametrize('state', ['new', 'clear', 'absent'])
def test_latest_effective_marks_are_used_on_current_and_previous_fields(monkeypatch, state):
    from diffeoforge import guided_feedback

    accepted_ref = dict(directory='accepted', candidate_id='fit', target='shape.vtk')
    current_ref = dict(accepted_ref, directory='current')
    previous_ref = dict(accepted_ref, directory='previous')
    accepted = SimpleNamespace(attachment_comparison=dict(guided=dict(screen_trials_spent=1)))
    current = SimpleNamespace()
    monkeypatch.setattr(guided_feedback, 'verify_reference',
                        lambda ref: accepted if ref['directory'] == 'accepted' else current)
    monkeypatch.setattr(guided_feedback, 'reference', lambda *args: accepted_ref)
    cleared = state == 'clear'
    marks = ([dict(new='missing-projection'), dict(new='keep-good-tooth')]
             if state == 'new' else [])
    monkeypatch.setattr(guided_feedback, 'region_state',
                        lambda parent, identifier, target: (deepcopy(marks), cleared))
    calls = []

    def compare(first, second, *, regions=None):
        calls.append((second, deepcopy(regions)))
        row = dict(mean=.01, p95=.01, p99=.01, regional_tail=.01, regions={})
        surface = dict(diagonal=1., repeats=[dict(row), dict(row)], warnings=[])
        return dict(accepted=surface, current=surface, agreement=surface,
                    accepted_local=False, accepted_controls=10, current_controls=10,
                    objective_tail=[], original_sha256='same', template_sha256='same')

    monkeypatch.setattr(diagnosis, '_compare', compare)
    value = dict(reviews=[dict(filename='shape.vtk', directory='accepted', candidate_id='fit')])
    diagnosis.diagnose(None, value, current_ref, previous_ref)
    expected = marks if marks or cleared else None
    assert calls == [(current_ref, expected), (previous_ref, expected)]


def test_current_mark_measurement_is_part_of_the_geometry_cache(tmp_path, monkeypatch):
    """Reuse the real public triangle/cache fixture, then change only its annotations."""
    from test_pilot_common_diagnosis import (
        test_bound_geometry_cache_rechecks_output_original_approval_and_target as exercise,
    )

    from diffeoforge import guided_response

    original = diagnosis._compare
    calls = []
    mark = dict(version='surface-region-v2', source_sha256='',
                space='original_mesh_coordinates', center=[.3, .3, 0.], radius=1.,
                symptom='detail', purpose='problem')

    def measured(ref, regions):
        calls.append((deepcopy(ref), deepcopy(regions)))
        return dict(baseline=[dict(region=r, repeats=[dict(original_to_fit_p95=.1,
            fit_to_original_p95=.1)] * 2) for r in regions])

    monkeypatch.setattr(guided_response, 'measured', measured)

    def compare(a, b):
        first = original(a, b)
        # This fixture's first two calls exercise a cache hit on unchanged bytes.
        if not calls:
            from diffeoforge.mesh import sha256_file

            region = dict(mark, source_sha256=sha256_file(tmp_path/'accepted'/'original.vtk'))
            new = original(a, b, regions=[region])
            assert new['marked_current'][0]['region'] == region
            assert original(a, b, regions=[region]) == new
            assert len(calls) == 2  # One measurement per field, no repeat on cache hit.
            with pytest.raises(ValueError, match='Region source'):
                original(a, b, regions=[dict(region, source_sha256='0' * 64)])
            assert len(calls) == 2
            cleared = original(a, b, regions=[])
            assert 'marked_current' not in cleared
        return first

    monkeypatch.setattr(diagnosis, '_compare', compare)
    exercise(tmp_path, monkeypatch)
