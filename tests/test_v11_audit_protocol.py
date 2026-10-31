import chess
import chess.pgn
import hashlib
import json
import pytest
from scripts import validate_v11_audit as protocol
from scripts.validate_v11_audit import SHAS, SHARDS, PAIRS, SECONDS, openings, outcome, stats


def test_manifest_and_schedule():
    assert len(SHAS) == len(set(SHAS.values())) == 4
    assert PAIRS == 50 and SHARDS == 10 and SECONDS == .2
    assert len(openings()) == 50
    assert {x['id'] for x in openings()} == set(range(50))


def test_win_metric_keeps_draws_errors_and_incompletes_in_denominator():
    rows=[dict(outcome=x) for x in ('win','draw','loss','error','incomplete')]
    score=stats(rows)
    assert score['win_percent'] == 20 and score['score_percent'] == 30
    assert score['errors'] == 1 and score['incomplete'] == 1
    assert outcome(chess.Board(),chess.WHITE) == ('incomplete','*','move_cap_incomplete')
    assert outcome(chess.Board(),chess.WHITE,'bad') == ('error','*','engine_error')


def test_pgn_revalidator_checks_telemetry_identity_even_with_valid_hash(tmp_path, monkeypatch):
    board=chess.Board()
    for move in ('e4','e5','Qh5','Nc6','Bc4','Nf6'):
        board.push_san(move)
    fen=board.fen()
    monkeypatch.setattr(protocol,'openings',lambda:[dict(id=0,fen=fen)])
    game=chess.pgn.Game();game.setup(board)
    move=board.parse_san('Qxf7#');game.add_variation(move);board.push(move)
    game.headers.update(GameID='test',GMVariant='both',GMSourceSHA=SHAS['both'],
        OpponentSHA256=protocol.SF_SHA256,OpeningID='0',TimeSeconds='.2',SkillLevel='5',
        Result='1-0',Termination='CHECKMATE')
    # Match canonical string representation produced by the tournament.
    game.headers['TimeSeconds']=str(SECONDS)
    (tmp_path/'all-games.pgn').write_text(str(game)+'\n\n')
    trace=dict(game_id='test',ply=0,engine='both',elapsed_seconds=.201,
               requested_seconds=SECONDS,move=move.uci())
    (tmp_path/'moves.jsonl').write_text(json.dumps(trace)+'\n')
    row=dict(game_id='test',opening_id=0,variant='both',color='white',
             outcome='win',result='1-0',termination='CHECKMATE',plies=1,error=None)
    summary=dict(shard=0,versions=SHAS,seconds=SECONDS,
        manifest_sha256=protocol.digest(protocol.MANIFEST),opponent_sha256=protocol.SF_SHA256,
        pgn_sha256=protocol.digest(tmp_path/'all-games.pgn'),
        moves_sha256=protocol.digest(tmp_path/'moves.jsonl'),games=[row])
    (tmp_path/'summary.json').write_text(json.dumps(summary))
    protocol.verify_shard(tmp_path,0)
    trace['engine']='stockfish'  # Move belongs to White GM, not the opponent.
    (tmp_path/'moves.jsonl').write_text(json.dumps(trace)+'\n')
    summary['moves_sha256']=protocol.digest(tmp_path/'moves.jsonl')
    (tmp_path/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(AssertionError):
        protocol.verify_shard(tmp_path,0)
