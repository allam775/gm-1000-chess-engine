"""Candidate tactical search must retain chess legality and emergency defenses.

The historical 'best' moves are Stockfish diagnostic references, not exact
assertions on a small custom engine. The A/B match determines promotion.
"""
from __future__ import annotations
import json,subprocess
from pathlib import Path
import chess
import pytest

ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/'native/bin/gm1000-native'
FENS=[
'r2qk2r/1b4pp/1pn1p3/p2pp3/3P1P2/6QN/PP4PP/1BR1K2R b Kkq - 1 16',
'r3k2r/3p2pp/1pnpq3/p2n1p2/8/P4PP1/1P2BP1P/R1BQ1RK1 b kq - 8 16',
'r1b2rk1/3nq1pp/p1pbp3/1p3pB1/Pn1PP3/1BN2P1N/1PQ3PP/1K1R3R b - - 2 15',
'r1b2r1k/5p1p/pqp2n1P/8/1p2P3/1N2bP1N/PPQ5/1K2RB1R b - - 2 22',
'rnb1kb1r/pp1p1p1p/1q1P1np1/2p5/4P3/5N2/PP3PPP/RNBQKB1R b KQkq - 0 7',
'8/P6k/8/8/8/8/8/7K w - - 0 1',
'8/8/8/4k3/8/8/4P3/4K3 w - - 0 1',
]
@pytest.fixture(scope='module',autouse=True)
def binary():
    if not BINARY.is_file():pytest.skip('Native C++ candidate not compiled')

@pytest.mark.parametrize('fen',FENS)
def test_candidate_legal_root_on_difficult_positions(fen):
    r=json.loads(subprocess.check_output([str(BINARY),'--bench',fen,'200'],text=True,timeout=7))
    b=chess.Board(fen)
    assert chess.Move.from_uci(r['bestmove']) in b.legal_moves
    assert r['depth']>=1 and r['nodes']>0

@pytest.mark.parametrize(('fen','depth','expected'),[
    (chess.STARTING_FEN,4,197281),
    ('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1',3,97862),
    ('8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1',4,43238),
])
def test_native_move_generation_unchanged(fen,depth,expected):
    r=subprocess.check_output([str(BINARY),'--perft',fen,str(depth)],text=True,timeout=15)
    assert int(r.strip())==expected

def test_simple_tactical_forced_mate():
    b=chess.Board()
    for san in ('e4','e5','Qh5','Nc6','Bc4','Nf6'):b.push_san(san)
    r=json.loads(subprocess.check_output([str(BINARY),'--bench',b.fen(),'200'],text=True,timeout=8))
    assert r['bestmove']=='h5f7'
    assert r['score']>29000

def test_queen_promotion_available_in_quiescence():
    fen='8/P6k/8/8/8/8/8/7K w - - 0 1'
    r=json.loads(subprocess.check_output([str(BINARY),'--bench',fen,'200'],text=True,timeout=8))
    assert r['bestmove']=='a7a8q'