from copy import deepcopy

from diffeoforge.pilot_region_scope import summary


def test_mixed_point_instructions_keep_editor_letters_and_active_subset():
    regions = [dict(center=[i, 0, 0], radius=1, purpose=role) for i,role in enumerate(
        ['problem', 'fixed', 'problem', 'preserve'])]
    before = deepcopy(regions)
    result = summary(dict(instruction_regions=regions, focus_regions=[regions[2]]))
    assert result['active'] == ['C'] and result['fixed'] == ['B']
    assert result['shape'] == ['D'] and result['waiting'] == ['A']
    assert 'improve C' in result['text'] and 'keep B in place' in result['text']
    assert regions == before


def test_all_problem_marks_active_does_not_invent_a_later_step():
    regions = [dict(center=[i, 0, 0], radius=1) for i in (0, 1)]
    result = summary(dict(instruction_regions=regions, focus_regions=regions))
    assert result['active'] == ['A', 'B'] and not result['waiting']
    assert 'later step' not in result['text']
