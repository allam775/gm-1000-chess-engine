"""Configuration and scoring invariants, independent of engine evaluation."""
from scripts.validate_v09_stockfish_levels import SHA_V08,SHA_V09, SETTINGS, single_score, result_for, summary_stats
import chess

def test_two_distinct_frozen_versions_and_matched_schedules():
    assert SHA_V08 != SHA_V09
    assert SETTINGS[5]['pairs']==50 and SETTINGS[5]['shards']*SETTINGS[5]['per_shard']==50
    assert SETTINGS[10]['pairs']==30 and SETTINGS[10]['shards']*SETTINGS[10]['per_shard']==30
    assert SETTINGS[5]['seed']!=SETTINGS[10]['seed']

def test_no_implicit_draws_for_errors_or_incompletes():
    rows=[dict(color='white',outcome='win'),dict(color='white',outcome='draw'),
          dict(color='white',outcome='loss'),dict(color='black',outcome='error'),
          dict(color='black',outcome='incomplete')]
    s=summary_stats(rows)
    assert (s['games'],s['completed'],s['errors'],s['incomplete'])==(5,3,1,1)
    assert s['score_percent']==50.
    assert s['by_color']['black']['score_percent'] is None

def test_actual_board_terminal_required():
    b=chess.Board()
    assert result_for(b,chess.WHITE,None)==('incomplete','*','move_cap_incomplete')
    assert result_for(b,chess.WHITE,'test')==('error','*','engine_error')
    for m in ('f3','e5','g4','Qh4#'):b.push_san(m)
    assert result_for(b,chess.BLACK,None)==('win','0-1','CHECKMATE')
    assert result_for(b,chess.WHITE,None)==('loss','0-1','CHECKMATE')

def test_score_math():
    assert single_score('win')==1. and single_score('draw')==.5 and single_score('loss')==0.
def test_workflow_shard_matrix_matches_validator():
    """Guard against missing tournament shards: every opening must be played."""
    import re
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/native-v09-holdout.yml').read_text()
    for skill in (5, 10):
        section = workflow.split(f'  skill{skill}:', 1)[1].split(f'  aggregate{skill}:', 1)[0]
        match = re.search(r'(?m)^\s*shard:\s*\[([0-9, ]+)\]\s*$', section)
        assert match is not None, f'Skill{skill} matrix not found'
        actual = [int(x.strip()) for x in match.group(1).split(',')]
        expected = list(range(SETTINGS[skill]['shards']))
        assert actual == expected, f'Skill{skill} scheduled {actual}, expected {expected}'
