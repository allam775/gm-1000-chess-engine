"""Keep the faster draw check semantically equivalent at important boundaries."""
import chess
from engine.search import Engine


def test_fast_draw_check_no_false_repetition():
    e = Engine()
    b = chess.Board()
    assert not e._drawn(b)
    for san in ('Nf3', 'Nf6', 'Ng1', 'Ng8'):
        b.push_san(san)
    assert not e._drawn(b)
    for san in ('Nf3', 'Nf6', 'Ng1', 'Ng8'):
        b.push_san(san)
    assert e._drawn(b)


def test_fast_draw_check_halfmove_and_insufficient():
    e = Engine()
    assert e._drawn(chess.Board('4k3/8/8/8/8/8/8/4K3 w - - 0 1'))
    assert e._drawn(chess.Board('4k3/8/8/8/8/8/4P3/4K3 w - - 100 51'))
