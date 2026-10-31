"""Integration test: the deployed game memory must actually affect UCI search."""
from pathlib import Path

import chess

from engine.search import Engine

ROOT = Path(__file__).resolve().parents[1]


def test_stored_grandmaster_memory_available_during_real_search():
    file = ROOT / 'data/position_memory.json'
    assert file.is_file(), 'The grandmaster position database must be committed to GitHub'
    engine = Engine(book_path=ROOT / 'data/opening_book.json', memory_path=file)
    board = chess.Board()
    remembered = engine.memory_moves(board)
    assert remembered, 'Expected some stored named-grandmaster first moves'
    assert all(move in board.legal_moves and observations > 0 for move, observations in remembered)
    assert engine._memory['source_games'] == 160
    assert engine._memory['holdout_games_excluded'] == 40
    result = engine.search(board, time_limit=None, depth=1, allow_book=True)
    assert result.move in board.legal_moves
    assert result.depth == 1, 'Memorized moves should be checked by search, not blindly returned'
    assert not result.book
    engine.memory_enabled = False
    assert engine.memory_moves(board) == []
    engine.new_game()
    assert engine._memory is None
