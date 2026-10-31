"""Independent legal exchange oracle and reproduced audit failures.

The production LVA estimate is used only for ordering. Equality to the exact
capture-tree oracle is asserted on these deliberately small exchange fixtures,
not claimed for arbitrary tactical positions.
"""
import subprocess
from pathlib import Path

import chess
import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'native/bin/gm1000-native'
VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 335,
          chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000}


def captured_value(board, move):
    return VALUES[chess.PAWN] if board.is_en_passant(move) else VALUES[board.piece_type_at(move.to_square)]


def exchange_oracle(board, move):
    """Exact optional legal recaptures on the same square, with promotions."""
    target = move.to_square
    gain = captured_value(board, move)
    if move.promotion:
        gain += VALUES[move.promotion] - VALUES[chess.PAWN]
    child = board.copy()
    child.push(move)
    replies = [m for m in child.legal_moves if m.to_square == target and child.is_capture(m)]
    return gain - max([0] + [exchange_oracle(child, m) for m in replies])


@pytest.mark.parametrize('fen,uci,expected', [
    # The king may not recapture on a bishop-defended square.
    ('5k2/4p3/8/8/1B6/8/8/K3R3 w - - 0 1', 'e1e7', 100),
    # The e8 rook may not leave the eighth rank and expose king a8.
    ('k3r2R/4p3/8/8/8/8/8/K3Q3 w - - 0 1', 'e1e7', 100),
    # A genuinely legal king recapture must still be counted.
    ('5k2/4p3/8/8/8/8/8/K3R3 w - - 0 1', 'e1e7', -400),
    ('4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1', 'e1e2', 900),
    ('4r1k1/4p3/8/8/8/8/8/4Q1K1 w - - 0 1', 'e1e7', -800),
    ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1', 'e5d6', 100),
    ('1r5k/P7/8/8/8/8/8/7K w - - 0 1', 'a7b8q', 1300),
    ('1r5k/P7/8/8/8/8/8/7K w - - 0 1', 'a7b8n', 720),
])
def test_legal_exchange_against_capture_tree(fen, uci, expected):
    assert ENGINE.is_file(), 'Build native engine before running audit regressions'
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    assert board.is_valid() and move in board.legal_moves
    assert exchange_oracle(board, move) == expected
    answer = subprocess.check_output([str(ENGINE), '--see', fen, uci], text=True, timeout=5)
    assert int(answer) == expected


def test_tt_clock_and_history_context(tmp_path):
    binary = tmp_path / 'context-probe'
    subprocess.run([
        'g++', '-O2', '-std=c++17', '-pthread', '-Wno-return-type',
        '-I', str(ROOT / 'native/third_party'),
        str(ROOT / 'tests/native_audit_context_probe.cpp'), '-o', str(binary),
    ], check=True, timeout=60)
    # Assertions deliberately enabled in this diagnostic executable.
    output = subprocess.check_output([str(binary)], text=True, timeout=10)
    assert 'warm99=0 cold99=0' in output
