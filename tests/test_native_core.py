"""Cross-validate the independent GM-1000 native search against python-chess.

Unit tests compare chess rules, terminal behavior, UCI compliance and whether
returned moves are legal, not strength. The benchmark/tournament is separate.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import time

import chess
import chess.engine
import pytest

ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/'native/bin/gm1000-native'
START=chess.STARTING_FEN
KIWIPETE='r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1'
PROMOTIONS='rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8'
EP='8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1'

@pytest.fixture(scope='module',autouse=True)
def compiled_native():
    if not BINARY.is_file():
        pytest.skip('Compile native engine first: g++ -std=c++17 -O3 -DNDEBUG -pthread -I native/third_party native/gm1000.cpp -o native/bin/gm1000-native')

@pytest.mark.parametrize(('fen','depth','expected'),[
    (START,1,20),(START,2,400),(START,3,8902),(START,4,197281),
    (KIWIPETE,1,48),(KIWIPETE,2,2039),(KIWIPETE,3,97862),
    (PROMOTIONS,3,62379), (EP,4,43238),
])
def test_move_generation_against_independent_reference(fen,depth,expected):
    r=subprocess.run([str(BINARY),'--perft',fen,str(depth)],capture_output=True,text=True,check=True,timeout=15)
    assert int(r.stdout.strip())==expected

def test_depth_search_mate_in_one():
    b=chess.Board()
    for san in ('e4','e5','Qh5','Nc6','Bc4','Nf6'):
        b.push_san(san)
    r=json.loads(subprocess.check_output([str(BINARY),'--bench',b.fen(),'100'],text=True,timeout=5))
    assert r['bestmove']=='h5f7'
    assert r['score']>=29000

def test_native_performance_result_legal_and_timely():
    b=chess.Board()
    r=json.loads(subprocess.check_output([str(BINARY),'--bench',b.fen(),'100'],text=True,timeout=5))
    assert chess.Move.from_uci(r['bestmove']) in b.legal_moves
    assert r['depth']>=1
    assert 0<r['seconds']<2.0
    assert r['nodes']>0

def test_uci_adapter_supports_python_chess():
    with chess.engine.SimpleEngine.popen_uci(str(BINARY),timeout=10) as engine:
        b=chess.Board()
        b.push_san('e4');b.push_san('c5');b.push_san('Nf3')
        r=engine.play(b,chess.engine.Limit(time=0.1))
        assert r.move in b.legal_moves
        board=chess.Board()
        for san in ('e4','e5','Qh5','Nc6','Bc4','Nf6'):
            board.push_san(san)
        mate=engine.play(board,chess.engine.Limit(depth=2))
        assert mate.move==chess.Move.from_uci('h5f7')

def test_native_special_moves_are_legal():
    cases=[KIWIPETE,PROMOTIONS,EP,START]
    with chess.engine.SimpleEngine.popen_uci(str(BINARY),timeout=10) as e:
        for fen in cases:
            b=chess.Board(fen)
            r=e.play(b,chess.engine.Limit(time=.05))
            assert r.move in b.legal_moves