"""Prospective effort includes old warm seeds; old receipts keep their native counters."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from diffeoforge import guided_feedback
from diffeoforge import pilot_common_model as common
from diffeoforge import pilot_iteration_accounting as effort
from diffeoforge import reference_calibration_study as study


def chain(monkeypatch):
    snapshots = {}

    def saved(name, local, strategy=None, recorded=None):
        metrics = dict(final_iteration=local, maximum_iterations=local)
        if recorded is not None:
            metrics['iteration_accounting'] = dict(total_iterations=recorded)
        candidate = SimpleNamespace(candidate_id='field', status='completed', metrics=metrics)
        snapshot = SimpleNamespace(study_directory=Path(name), candidates=(candidate,),
            attachment_comparison=dict(methods={'field': 'varifold'}, guided=dict(
                strategy=strategy or {})))
        snapshots[name] = snapshot
        return snapshot, candidate

    def ref(name):
        return dict(directory=name, candidate_id='field')

    monkeypatch.setattr(guided_feedback, 'verify_reference',
                        lambda r: snapshots[r['directory']])
    monkeypatch.setattr(study, 'load_reference_calibration_study',
                        lambda root: snapshots[str(root)])
    base = saved('base', 120)
    old_optional = saved('old-optional', 240,
                         dict(optimization=dict(reference=ref('base'), iterations=240)))
    old_common = saved('old-common', 120, dict(common_model_step=dict(
        version=common.LEGACY_VERSION, reference=ref('old-optional'),
        previous_iterations=240, additional_iterations=120)), recorded=360)
    return saved, ref, base, old_optional, old_common


def manifest(strategy):
    return dict(plan=dict(stages=[dict(candidates=[dict(candidate_id='field')])]),
                attachment_comparison=dict(guided=dict(strategy=strategy)))


def test_old_local_counter_does_not_erase_its_earlier_saved_seed(monkeypatch):
    _, _, base, optional, old_common = chain(monkeypatch)
    protected = deepcopy((base[1].metrics, optional[1].metrics, old_common[1].metrics))
    assert effort.total(optional[1].metrics) == 240
    assert effort.branch_total(*optional) == 360
    assert effort.total(old_common[1].metrics) == 360
    assert effort.branch_total(*old_common) == 480
    assert protected == (base[1].metrics, optional[1].metrics, old_common[1].metrics)


def test_old_prepared_offsets_stay_unchanged_but_new_successor_uses_full_branch(monkeypatch):
    _, ref, _, optional, old_common = chain(monkeypatch)
    legacy_optional = optional[0].attachment_comparison['guided']['strategy']
    legacy_common = old_common[0].attachment_comparison['guided']['strategy']
    assert effort.source(manifest(legacy_optional), 'field') is None
    assert effort.offset(manifest(legacy_common), 'field') == 240
    future = dict(common_model_step=dict(version=common.VERSION, reference=ref('old-common'),
                                        previous_iterations=480, additional_iterations=120))
    assert effort.offset(manifest(future), 'field') == 480
    measured = dict(final_iteration=120, maximum_iterations=120)
    effort.annotate(measured, 480)
    assert measured['iteration_accounting']['total_iterations'] == 600
    assert measured['final_iteration'] == 120


def test_cyclic_counter_lineage_is_rejected_without_computation(monkeypatch):
    saved, ref, *_ = chain(monkeypatch)
    cycle = saved('cycle', 120, dict(optimization=dict(reference=ref('cycle'), iterations=120)))
    with pytest.raises(ValueError, match='Cyclic'):
        effort.branch_total(*cycle)
