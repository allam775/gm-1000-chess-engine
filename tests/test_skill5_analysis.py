"""Basic group statistics and phase boundaries for Skill-5 forensic study."""
from scripts.analyze_skill5_losses import phase, describe_group


def test_phase_boundaries():
    assert phase(1) == 'opening'
    assert phase(20) == 'opening'
    assert phase(21) == 'middlegame'
    assert phase(60) == 'middlegame'
    assert phase(61) == 'late'


def test_empty_group():
    group = describe_group([])
    assert group['games'] == 0
    assert group['gm']['moves_analyzed'] == 0
    assert group['memory']['gm_moves_total'] == 0