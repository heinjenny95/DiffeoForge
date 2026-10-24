"""Regional response and mark retention; public synthetic cases, no native fitting."""
import copy
from types import SimpleNamespace

import pytest
from test_guided_feedback import decision
from test_guided_pilot import run_batch
from test_interactive_pilot import geometry_receipt, initial
from test_pilot_region_feedback import patch, reject

from diffeoforge import guided_feedback as feedback
from diffeoforge import guided_response as response
from diffeoforge import reference_calibration_study as study
from diffeoforge import reference_guided_pilot as guided


def metric(mean=1., tail=2., reverse=1.):
    repeat = dict(original_to_fit_mean=mean, original_to_fit_p95=tail,
                  original_to_fit_p99=tail, fit_to_original_p95=reverse)
    return dict(baseline=[dict(region={'source': 'same-patch'}, diagonal=10.,
                              repeats=[repeat, repeat])],
                global_baseline=dict(repeats=[dict(mean=1., p95=2., p99=3.)] * 2))


@pytest.mark.parametrize(('mean', 'tail', 'expected'), [
    (.7, 2., 'improved'), (1., 2., 'unchanged'), (1.2, 2.3, 'worse'),
    (.7, 2.3, 'tradeoff'),
])
def test_response_distinguishes_missing_detail_tail_from_average_gain(mean, tail, expected):
    assert response.compare(metric(), metric(mean, tail))['status'] == expected


def test_sampling_uncertainty_and_global_regression_do_not_become_success():
    before, after = metric(), metric(.94)
    before['baseline'][0]['repeats'][0] = dict(
        before['baseline'][0]['repeats'][0], original_to_fit_mean=.91)
    assert response.compare(before, after)['status'] == 'unchanged'
    after['global_baseline']['repeats'] = [dict(mean=2., p95=4., p99=6.)] * 2
    assert response.compare(before, after)['global_worse']
    after['baseline'][0]['region'] = {'source': 'another-patch'}
    with pytest.raises(ValueError, match='identical'):
        response.compare(before, after)


def case(family, status, *, outcome='same', global_worse=False):
    return dict(goal=family, family=family, outcome=outcome,
                response=dict(status=status, global_worse=global_worse))


def test_regional_failures_override_fixed_parameter_rotation():
    # Smaller attachment width worsened the marked part despite global improvement.
    rows = [case('detail', 'worse'), case('weight', 'unchanged')]
    family, reason = response.choose(rows, 'detail')
    assert family in {'local_motion', 'density'}
    assert 'did not reliably reduce' in reason
    rows.extend([case('local_motion', 'worse'), case('density', 'improved')])
    assert response.choose(rows, 'detail')[0] == 'density'
    rows[-1]['outcome'] = 'worse'  # Human rejection vetoes a favorable metric.
    assert response.choose(rows, 'detail')[0] == 'weight'


def test_all_stalled_families_explain_input_check_without_a_dead_end():
    family, reason = response.choose([case(g, 'unchanged') for g in
                                     ['detail', 'weight', 'local_motion', 'density']], 'detail')
    assert family and 'Check alignment and the template' in reason
    assert 'optional' in reason


def test_new_marks_bound_geometry_replay_without_discarding_history(monkeypatch):
    calls = []
    monkeypatch.setattr(
        response, "measured", lambda reference, regions: calls.append(reference) or {}
    )
    monkeypatch.setattr(
        response, "compare", lambda *_: dict(status="unchanged", global_worse=False)
    )
    reference = dict(target="shape.vtk", method="varifold", id="preferred")
    cases = [
        dict(fit=dict(reference, id=i), target="shape.vtk", method="varifold", family="detail")
        for i in range(60)
    ]
    result, evidence = response.history(cases, reference, [dict(mark="new")])
    assert len(result) == 60 and len(evidence) == 2
    assert len(calls) == 3  # retained baseline plus the two latest contrasts
    assert result[0] == cases[0] and all(c["fit"] == r["fit"]
                                       for c, r in zip(cases, result, strict=True))


def marked_chain(tmp_path, monkeypatch):
    base = reject(run_batch(initial(tmp_path), monkeypatch), 'guided-varifold', marked=True)
    geometry_receipt(base, 'guided-varifold', monkeypatch)
    child = guided.next_action(base.study_directory, 'adaptive_recover', 'guided-varifold',
                               goal='goal:detail')
    child = run_batch(child, monkeypatch)
    return base, child


def test_empty_feedback_and_empty_re_review_preserve_patches(tmp_path, monkeypatch):
    base, child = marked_chain(tmp_path, monkeypatch)
    target = guided.record(child)['target']
    expected = feedback.regions(child, 'guided-varifold', target)
    child = feedback.save_feedback(child.study_directory, 'guided-varifold',
                                   decision(base, child, 'same') | dict(problem_regions={}))
    assert feedback.regions(child, 'guided-varifold', target) == expected
    child = reject(child)  # A separate suitability decision must not delete marks.
    reopened = study.load_reference_calibration_study(child.study_directory)
    assert feedback.regions(reopened, 'guided-varifold', target) == expected


def test_explicit_clear_survives_successor_and_empty_feedback(tmp_path, monkeypatch):
    base, child = marked_chain(tmp_path, monkeypatch)
    target = guided.record(child)['target']
    child = feedback.save_feedback(child.study_directory, 'guided-varifold',
        decision(base, child, 'same') | dict(problem_regions={}, cleared_region_subjects=[target]))
    child = reject(child)
    assert feedback.region_state(child, 'guided-varifold', target) == ([], True)
    follow = guided.next_action(child.study_directory, 'adaptive_recover', 'guided-varifold',
                                goal='goal:weight')
    assert guided.record(follow)['feedback']['regions_cleared']
    assert feedback.region_state(follow, 'guided-varifold', target) == ([], True)


def test_old_ambiguous_empty_feedback_recovers_history_without_editing_it(tmp_path, monkeypatch):
    base, child = marked_chain(tmp_path, monkeypatch)
    form = child.plan.selected_pilot_subjects[0]
    current = feedback.reference(child, 'guided-varifold')
    legacy = decision(base, child, 'same') | dict(current=current, problem_regions={},
        anatomical_approval_created=False, optimizer_started=False)
    study._append_event(child.study_directory, 'guided_fit_feedback', legacy)
    before = (child.study_directory / study.STUDY_EVENTS).read_bytes()
    assert feedback.regions(study.load_reference_calibration_study(child.study_directory),
                            'guided-varifold', form.filename) == [patch(form.sha256)]
    assert (child.study_directory / study.STUDY_EVENTS).read_bytes() == before


def test_history_uses_same_new_patch_for_all_results_and_rejects_other_methods(monkeypatch):
    calls = []
    anchor = dict(target='form', method='current', directory='anchor')
    a, b = dict(anchor, directory='a'), dict(anchor, directory='b')
    def measured(ref, marks):
        calls.append((ref['directory'], copy.deepcopy(marks)))
        return metric(.7 if ref == b else 1.)
    monkeypatch.setattr(response, 'measured', measured)
    rows = [dict(case('detail', 'unchanged'), fit=a, target='form', method='current'),
            dict(case('density', 'unchanged'), fit=b, target='form', method='current'),
            dict(fit=a, target='form', method='varifold')]
    result, evidence = response.history(rows, anchor, [{'new': 'patch'}])
    assert [r['status'] for r in evidence] == ['unchanged', 'improved']
    assert all(p == [{'new': 'patch'}] for _, p in calls)
    assert 'response' not in result[-1] and 'response' in result[0]


def test_measurement_cache_never_skips_identity_validation_and_is_patch_bound(monkeypatch):
    from diffeoforge import pilot_recovery
    calls = []
    parent = SimpleNamespace(candidates=[SimpleNamespace(candidate_id='test', metrics={})])
    monkeypatch.setattr(feedback, 'verify_reference', lambda r: calls.append('verify') or parent)
    monkeypatch.setattr(pilot_recovery, 'capture',
                        lambda *a, **k: calls.append('measure') or metric())
    ref = dict(directory='cache-test', candidate_id='test', target='form')
    response.measured(ref, [{'cache': 'one'}])
    response.measured(ref, [{'cache': 'one'}])
    assert calls == ['verify', 'measure', 'verify']
    response.measured(ref, [{'cache': 'two'}])
    assert calls[-2:] == ['verify', 'measure']
    def changed(_ref):
        raise ValueError('Changed source bytes')
    monkeypatch.setattr(feedback, 'verify_reference', changed)
    with pytest.raises(ValueError, match='Changed source'):
        response.measured(ref, [{'cache': 'one'}])


def test_empty_history_is_scanned_once_instead_of_recursively_revisiting_prefixes(monkeypatch):
    from pathlib import Path

    snapshots = [SimpleNamespace(study_directory=Path(str(i)), region_edits={},
                 problem_regions={}, candidates=[SimpleNamespace(candidate_id='fit')])
                 for i in range(24)]
    loaded = []
    monkeypatch.setattr(feedback, '_local_events', lambda *a: [])
    monkeypatch.setattr(feedback, 'sha256_file', lambda p: 'bound')
    monkeypatch.setattr(guided, 'record', lambda s: dict(target='form', origin='same',
        history=[dict(directory=str(i), manifest_sha256='bound')
                 for i in range(int(str(s.study_directory)))]))
    def load(path):
        loaded.append(str(path))
        return snapshots[int(str(path))]
    monkeypatch.setattr(study, 'load_reference_calibration_study', load)
    assert feedback.region_state(snapshots[-1], 'fit', 'form') == ([], False)
    assert len(loaded) == 23 and len(set(loaded)) == 23
