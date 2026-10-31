from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import chess
import chess.pgn
import pytest

from engine.search import Engine, MATE, book_key, evaluate
from scripts.build_book import Candidate, create_book, parse_candidates, select_round_robin

ROOT = Path(__file__).resolve().parents[1]


def test_initial_legal_move():
    board = chess.Board()
    bot = Engine()
    bot.own_book = False
    result = bot.search(board, time_limit=None, depth=1)
    assert result.move in board.legal_moves
    assert result.depth == 1
    assert board.fen() == chess.STARTING_FEN


def test_no_moves_when_mated():
    board = chess.Board()
    for san in ('f3', 'e5', 'g4', 'Qh4#'):
        board.push_san(san)
    assert Engine().search(board).move is None


def test_quiet_mate_in_one():
    # White's queen can capture f7 to deliver checkmate.
    board = chess.Board()
    for san in ('e4', 'e5', 'Qh5', 'Nc6', 'Bc4', 'Nf6'):
        board.push_san(san)
    bot = Engine()
    bot.own_book = False
    result = bot.search(board, time_limit=None, depth=2)
    assert result.move == chess.Move.from_uci('h5f7')
    assert result.score >= MATE - 5


def test_eval_material_sign():
    board = chess.Board('4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1')
    assert evaluate(board) > 800
    board.turn = chess.BLACK
    assert evaluate(board) < -800


def test_search_preserves_board():
    board = chess.Board()
    board.push_san('d4')
    snapshot = board.fen()
    bot = Engine()
    bot.own_book = False
    bot.search(board, time_limit=.05, depth=5)
    assert board.fen() == snapshot


def test_position_key_excludes_move_counters():
    a = chess.Board()
    b = chess.Board('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 37 15')
    assert book_key(a) == book_key(b)


def test_book_frequencies_and_legality(tmp_path):
    a = Candidate('Carlsen', {}, ('e2e4', 'e7e5'), 'hash-a', 25)
    b = Candidate('Fischer', {}, ('e2e4', 'c7c5'), 'hash-b', 20)
    book = create_book([a, b])
    start = book_key(chess.Board())
    assert book['positions'][start] == {'e2e4': 2}
    path = tmp_path / 'opening_book.json'
    path.write_text(json.dumps(book))
    bot = Engine(book_path=path)
    assert bot.book_move(chess.Board()) == chess.Move.from_uci('e2e4')
    bot.own_book = False
    assert bot.book_move(chess.Board()) is None


def test_candidate_round_robin_unique():
    a = Candidate('Carlsen', {}, ('e2e4',), 'same', 1)
    b = Candidate('Kasparov', {}, ('e2e4',), 'same', 2)
    c = Candidate('Kasparov', {}, ('d2d4',), 'other', 3)
    selected = select_round_robin({'Carlsen': [a], 'Kasparov': [b, c]}, 2)
    assert len(selected) == 2
    assert len({i.fingerprint for i in selected}) == 2


def test_pgn_selection_parsing():
    game = chess.pgn.Game()
    game.headers['Event'] = 'World Chess Championship'
    game.headers['Result'] = '1-0'
    board = game.board()
    node = game
    for _ in range(10):
        for san in ('Nf3', 'Nf6', 'Ng1', 'Ng8'):
            move = board.parse_san(san)
            node = node.add_variation(move)
            board.push(move)
    games, scanned = parse_candidates(str(game), 'Carlsen', 100)
    assert scanned == 1
    assert len(games) == 1
    assert len(games[0].moves) == 40


def test_uci_handshake_and_move():
    p = subprocess.Popen([sys.executable, '-u', '-m', 'engine.uci'], cwd=ROOT,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        p.stdin.write('uci\nisready\nsetoption name OwnBook value false\nposition startpos\ngo depth 1\n')
        p.stdin.flush()
        lines = []
        # Time-limited CI command will terminate a hung engine.
        for line in p.stdout:
            lines.append(line.strip())
            if line.startswith('bestmove '):
                break
        assert 'uciok' in lines
        assert 'readyok' in lines
        best = [s for s in lines if s.startswith('bestmove ')][0].split()[1]
        assert chess.Move.from_uci(best) in chess.Board().legal_moves
    finally:
        p.stdin.write('quit\n')
        p.stdin.flush()
        p.wait(timeout=5)


def test_uci_fen_position():
    from engine.uci import UCI
    uci = UCI()
    uci.process('position startpos moves e2e4 e7e5')
    board = chess.Board()
    board.push_uci('e2e4')
    board.push_uci('e7e5')
    assert uci.board.fen() == board.fen()
    uci.process('position fen 8/8/8/8/8/8/4k3/7K w - - 0 1')
    assert uci.board.king(chess.WHITE) == chess.H1
