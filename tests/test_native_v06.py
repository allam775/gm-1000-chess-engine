"""Executable independent native engine checks; skip when binary isn't compiled."""
import os
import subprocess
import chess
import chess.engine
import pytest

@pytest.fixture
def native():
    executable=os.environ.get("NATIVE_ENGINE")
    if not executable:pytest.skip("native C++ binary not compiled")
    with chess.engine.SimpleEngine.popen_uci(executable) as engine:
        yield engine

def test_perft_castling_and_enpassant():
    exe=os.environ.get("NATIVE_ENGINE")
    if not exe:pytest.skip("compiled binary absent")
    for depth,count in ((1,20),(2,400),(3,8902),(4,197281)):
        output=subprocess.check_output([exe,"--perft",str(depth)],text=True)
        assert int(output.strip())==count

@pytest.mark.parametrize("moves",[
    [],
    ["e4","e5","Nf3","Nc6"],
    ["d4","d5","c4","e6"],
    ["e4","c5","Nf3","d6","d4","cxd4","Nxd4"],
    ["f3","e5","g4"],
])
def test_native_returns_legal_move(native,moves):
    board=chess.Board()
    for san in moves:board.push_san(san)
    result=native.play(board,chess.engine.Limit(time=0.2))
    assert result.move in board.legal_moves
    assert board.is_valid()
