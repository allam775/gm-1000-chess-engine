"""Regression checks for future Stockfish 19 Skill-20 game-memory learning."""
import json
from pathlib import Path

import chess
from engine.search import Engine, book_key
from scripts.reconcile_stockfish19_memory import choose_preferred, player_points, side_score
from scripts.stockfish19_selfplay400 import varied_opening_positions


def test_outcome_correct_from_side_to_move():
    assert player_points('1-0', chess.WHITE)=='wins'
    assert player_points('1-0', chess.BLACK)=='losses'
    assert player_points('0-1', chess.BLACK)=='wins'
    assert player_points('0-1', chess.WHITE)=='losses'
    assert player_points('1/2-1/2', chess.BLACK)=='draws'
    assert player_points('*', chess.WHITE) is None
    assert side_score({'wins':2,'draws':1,'losses':1})==0.625


def test_old_gm_kept_when_stockfish_only_won_once():
    sf={'d2d4':{'observations':1,'wins':1}}
    old={'e2e4':{'count':20,'players':{'Carlsen':20}}}
    assert choose_preferred(sf,old,{'d2d4':5,'e2e4':20})[0]=='e2e4'
    assert choose_preferred(sf,old,{})[0]=='e2e4'


def test_stockfish_replaces_gm_only_with_verified_20cp_gain():
    sf={'d2d4':{'observations':3,'wins':2,'draws':1}}
    old={'e2e4':{'count':20,'players':{'Tal':20}}}
    selected,reason=choose_preferred(sf,old,{'d2d4':60,'e2e4':15})
    assert selected=='d2d4' and reason=='stockfish_evaluated_gain'


def test_retains_both_conflicting_moves_in_recall(tmp_path):
    board=chess.Board()
    key=book_key(board)
    gm={'schema':1,'source_games':560,'positions':{key:{'e2e4':{'count':40,'players':{'Carlsen':40}}}}}
    sf={
        'schema': 1,
        'positions': {
            key: {
                'preferred_move': 'd2d4',
                'selection_reason': 'stockfish_evaluated_gain',
                'candidates': {
                    'e2e4': {'grandmasters': {'count': 40}},
                    'd2d4': {'stockfish': {'wins': 3}},
                },
            },
        },
    }
    old=tmp_path/'old.json'; old.write_text(json.dumps(gm))
    new=tmp_path/'sf.json'; new.write_text(json.dumps(sf))
    engine=Engine(book_path=tmp_path/'none.json',memory_path=old,stockfish_memory_path=new)
    assert engine.memory_moves(board)[0][0]==chess.Move.from_uci('e2e4')
    assert engine._stockfish_preferred(board)==chess.Move.from_uci('d2d4')
    assert engine.search(board,time_limit=None,depth=1).move in board.legal_moves
    engine.stockfish_memory_enabled=False
    assert engine._stockfish_preferred(board) is None


def test_random_opening_generation_is_diverse_and_reproducible():
    root=Path(__file__).resolve().parents[1]
    book=json.loads((root/'data/opening_book.json').read_text(encoding='utf-8'))
    positions=varied_opening_positions(book,pairs=3,seed=44)
    second=varied_opening_positions(book,pairs=3,seed=44)
    assert positions==second
    assert len({p['epd'] for p in positions})==3
    assert all(p['opening_plies']>=8 for p in positions)
