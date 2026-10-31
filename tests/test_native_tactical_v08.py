"""v0.8 legal/correctness checks plus real forensic FENs from Stockfish19 audit.

Teacher moves are diagnostic, NOT enforced; timed chess choices are contingent
on hardware and the independent playing tournament is the strength gate.
"""
import json,subprocess
from pathlib import Path
import chess,pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'build/tournament/v08'
CRITICAL=[
 'r2r2k1/1b1n1pPp/1pp5/p7/P1P1Nq1P/RP1p1N2/5PP1/3Q1RK1 w - - 1 18',
 'r2qkb1r/pp3ppp/2n1p3/3n4/3P4/1QN2P2/PP3P1P/R1B1KB1R w KQkq - 0 10',
 '3rr1k1/p4ppp/2p1p2q/8/1P1P4/P3PPQ1/4K2P/R6R w - - 1 22',
 '1r5r/p1k2p2/8/1p4pp/2b5/q1p2Q2/2P2PPP/1R1R2K1 b - - 1 28',
 '2kr3r/pp3p1p/q1n1p1p1/2n1P3/5P2/5N2/PP2N1PP/R1BQK2R w KQ - 0 16',
 'r2qk2r/1b4pp/1pn1p3/p2pp3/3P1P2/6QN/PP4PP/1BR1K2R b Kkq - 1 16'
]
@pytest.fixture(scope='module',autouse=True)
def binary():
    if not NATIVE.is_file():pytest.skip('Compile experimental candidate first')
@pytest.mark.parametrize('fen',CRITICAL)
def test_critical_position_returns_legal_move(fen):
    x=json.loads(subprocess.check_output([str(NATIVE),'--bench',fen,'200'],text=True,timeout=7))
    assert chess.Move.from_uci(x['bestmove']) in chess.Board(fen).legal_moves
    assert x['depth']>=1 and x['nodes']>0
@pytest.mark.parametrize(('fen','depth','expected'),[
 (chess.STARTING_FEN,4,197281),
 ('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1',3,97862),
 ('8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1',4,43238),
])
def test_rules_match_reference(fen,depth,expected):
    r=subprocess.check_output([str(NATIVE),'--perft',fen,str(depth)],text=True,timeout=15)
    assert int(r.strip())==expected

def test_forced_mate_and_promotion():
    b=chess.Board()
    for m in ('e4','e5','Qh5','Nc6','Bc4','Nf6'):b.push_san(m)
    mate=json.loads(subprocess.check_output([str(NATIVE),'--bench',b.fen(),'200'],text=True,timeout=7))
    assert mate['bestmove']=='h5f7' and mate['score']>29000
    fen='8/P6k/8/8/8/8/8/7K w - - 0 1'
    promo=json.loads(subprocess.check_output([str(NATIVE),'--bench',fen,'200'],text=True,timeout=7))
    assert promo['bestmove']=='a7a8q'