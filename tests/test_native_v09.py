"""v0.9 correctness and regression tests, never fitted to Stockfish game scores."""
from __future__ import annotations
import json, subprocess
from pathlib import Path
import chess
import pytest

ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'native/bin/gm1000-native'

@pytest.fixture(scope='module',autouse=True)
def compiled():
    if not ENGINE.exists():pytest.skip('Native v0.9 not compiled')

@pytest.mark.parametrize(('fen','move','expected'),[
    ('4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1','e1e2',900),
    ('4r1k1/4p3/8/8/8/8/8/4Q1K1 w - - 0 1','e1e7',-800),
    ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1','e5d6',100),
    ('6k1/8/8/8/8/8/4r3/4R1K1 w - - 0 1','e1e2',500),
])
def test_exchange_simulation(fen,move,expected):
    assert chess.Move.from_uci(move) in chess.Board(fen).legal_moves
    output=subprocess.check_output([str(ENGINE),'--see',fen,move],text=True,timeout=5)
    assert int(output.strip())==expected

@pytest.mark.parametrize(('fen','depth','nodes'),[
    (chess.STARTING_FEN,4,197281),
    ('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1',3,97862),
    ('8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1',4,43238),
])
def test_unchanged_legal_move_generation(fen,depth,nodes):
    assert int(subprocess.check_output([str(ENGINE),'--perft',fen,str(depth)],text=True,timeout=15))==nodes

@pytest.mark.parametrize('fen',[
    'r2r2k1/1b1n1pPp/1pp5/p7/P1P1Nq1P/RP1p1N2/5PP1/3Q1RK1 w - - 1 18',
    'r2qkb1r/pp3ppp/2n1p3/3n4/3P4/1QN2P2/PP3P1P/R1B1KB1R w KQkq - 0 10',
    '1r5r/p1k2p2/8/1p4pp/2b5/q1p2Q2/2P2PPP/1R1R2K1 b - - 1 28',
    'rnb1kb1r/pp1p1p1p/1q1P1np1/2p5/4P3/5N2/PP3PPP/RNBQKB1R b KQkq - 0 7',
    '8/P6k/8/8/8/8/8/7K w - - 0 1',
    '8/8/8/4k3/8/8/4P3/4K3 w - - 0 1',
])
def test_candidate_never_returns_illegal_move(fen):
    x=json.loads(subprocess.check_output([str(ENGINE),'--bench',fen,'200'],text=True,timeout=10))
    assert chess.Move.from_uci(x['bestmove']) in chess.Board(fen).legal_moves
    assert x['depth']>=1 and x['nodes']>0

def test_forced_mate_and_queen_promotion():
    b=chess.Board()
    for san in ('e4','e5','Qh5','Nc6','Bc4','Nf6'):b.push_san(san)
    result=json.loads(subprocess.check_output([str(ENGINE),'--bench',b.fen(),'200'],text=True,timeout=10))
    assert result['bestmove']=='h5f7' and result['score']>29000
    prom='8/P6k/8/8/8/8/8/7K w - - 0 1'
    assert json.loads(subprocess.check_output([str(ENGINE),'--bench',prom,'200'],text=True,timeout=10))['bestmove']=='a7a8q'

def test_no_game_state_leak_through_ucinewgame():
    import chess.engine
    with chess.engine.SimpleEngine.popen_uci(str(ENGINE),timeout=15) as sf:
        assert 'GM-1000' in sf.id.get('name','')
        first=object();second=object()
        for round_id in (first,first,second):
            b=chess.Board()
            answer=sf.play(b,chess.engine.Limit(time=.15),game=round_id)
            assert answer.move in b.legal_moves
