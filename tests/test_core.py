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


def test_evaluation_components_reconstruct_original():
    from engine.search import evaluate_components
    b = chess.Board()
    b.push_san('e4')
    b.push_san('e5')
    b.push_san('Nf3')
    comps = evaluate_components(b)
    expected = sum(comps.values()) * (1 if b.turn == chess.WHITE else -1)
    assert evaluate(b) == expected
    assert evaluate(b, {name: 1.0 for name in comps}) == expected


def test_retired_outcome_learning_is_blocked(tmp_path):
    from engine.learning import empty_state, train_completed_pgn
    with pytest.raises(RuntimeError, match='retired'):
        train_completed_pgn(tmp_path / 'does-not-matter.pgn', empty_state())


def test_gm_position_sampling_is_champion_side_only():
    from scripts.study_gm_games import sample_plys, expert_color
    from scripts.build_book import Candidate
    g = Candidate('Carlsen', {'White': 'Carlsen, Magnus', 'Black': 'Other'},
                  tuple(['e2e4']*70), 'test-sha', 1.0)
    assert expert_color(g) == chess.WHITE
    assert all(p % 2 == 0 and p >= 24 for p in sample_plys(70, chess.WHITE))
    assert all(p % 2 == 1 and p >= 24 for p in sample_plys(70, chess.BLACK))


def test_pairwise_logistic_train_and_bounds():
    from scripts.study_gm_games import Sample, assess, optimize, softplus, sigmoid_minus
    n = 9
    expert = (1.0,) + (0.0,) * (n-1)
    alternative = (-1.0,) + (0.0,) * (n-1)
    samples = [Sample(str(i), 26, expert, (alternative,), 0.0, (0.0,))
               for i in range(35)]
    weights, history = optimize(samples, epochs=6, learning_rate=.05)
    assert weights['bishop_pair'] > 1.0
    assert all(.7 <= x <= 1.3 for x in weights.values())
    assert assess(samples, weights)['mean_pairwise_log_loss'] < assess(samples, {
        key: 1.0 for key in weights})['mean_pairwise_log_loss']
    assert 0 < sigmoid_minus(1) < .5
    assert abs(softplus(0)-0.6931471805599453) < 1e-9
    assert len(history) == 6


def test_untrained_default_ignores_legacy_outcome_file(tmp_path, monkeypatch):
    # New approved-only default is separate from old experimental state.
    from engine.search import Engine
    bot = Engine()
    assert bot.learning_path.name == 'approved_model.json'
    assert bot._load_learning()['weights'] == {}
    bot.new_game()
    assert bot._learning is None


def test_promotion_gate_rejects_weak_and_mismatched_results():
    from engine.promotion import check_strength_gate
    conf = {'stockfish_skill': 5, 'seconds_per_move': .2,
            'own_book': True, 'max_plies': 260}
    def result(wins, losses):
        return {'wins': wins, 'draws': 0, 'losses': losses, 'completed_games': wins+losses,
                'errors': 0, 'incomplete': 0, 'opponent': 'Stockfish', 'config': dict(conf)}
    report = {'offline_validation_gate': {'passes': True}}
    original, improved = result(20, 180), result(170, 30)
    assert check_strength_gate(report, original, improved)['promote']
    assert not check_strength_gate(report, result(110, 90), result(105, 95))['promote']
    wrong = result(170, 30)
    wrong['config']['stockfish_skill'] = 0
    assert not check_strength_gate(report, original, wrong)['promote']
    assert not check_strength_gate({'offline_validation_gate': {'passes': False}},
                                   original, improved)['promote']


def test_legacy_trainer_cannot_run_on_incomplete_games(tmp_path):
    from engine.learning import empty_state, train_completed_pgn
    p = tmp_path / 'incomplete.pgn'
    p.write_text('[Result "*"]\n\n*\n', encoding='utf-8')
    state = empty_state()
    with pytest.raises(RuntimeError, match='retired'):
        train_completed_pgn(p, state)
    assert state['epochs'] == 0


def test_round_robin_can_select_subset_of_gm_player_archives():
    from scripts.build_book import Candidate, select_round_robin
    players = {
        'Carlsen': [Candidate('Carlsen', {}, ('e2e4',), 'a', 1.0),
                    Candidate('Carlsen', {}, ('d2d4',), 'b', 1.0)],
        'Kasparov': [Candidate('Kasparov', {}, ('c2c4',), 'c', 1.0)],
    }
    # A subset should not need synthetic Capablanca/Morphy entries.
    result = select_round_robin(players, 3)
    assert len(result) == 3
    assert {x.fingerprint for x in result} == {'a', 'b', 'c'}


def test_grandmaster_position_memory_records_correct_color_and_counts(tmp_path):
    from engine.position_memory import build_position_memory, legal_memory_moves
    from scripts.build_book import Candidate
    moves = ('e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1c4', 'f8c5')
    game_a = Candidate('Carlsen', {'White':'Magnus Carlsen', 'Black':'Opp'}, moves, 'a', 1.0)
    game_b = Candidate('Carlsen', {'White':'Magnus Carlsen', 'Black':'Opp'}, moves, 'b', 1.0)
    memory = build_position_memory([game_a, game_b], max_plies=6)
    assert memory['source_games'] == 2
    assert memory['observations'] == 6
    assert memory['positions_count'] == 3
    assert memory['move_pairs_count'] == 3
    assert legal_memory_moves(chess.Board(), memory) == [(chess.Move.from_uci('e2e4'), 2)]
    board = chess.Board()
    board.push_uci('e2e4')
    # Black moves are absent: it was not the named grandmaster's turn.
    assert legal_memory_moves(board, memory) == []
    out = tmp_path / 'memory.json'
    out.write_text(json.dumps(memory))
    bot = Engine(book_path=tmp_path/'absent.json', memory_path=out)
    assert bot.memory_moves(chess.Board()) == [(chess.Move.from_uci('e2e4'), 2)]
    bot.memory_enabled = False
    assert bot.memory_moves(chess.Board()) == []


def test_position_memory_search_only_overrides_nearly_equal_evaluation(tmp_path):
    from engine.position_memory import choose_safe_recalled_move
    good = chess.Move.from_uci('e2e4')
    bad = chess.Move.from_uci('a2a3')
    memory = [(bad, 100), (good, 1)]
    assert choose_safe_recalled_move(memory, {bad: 20, good: 60}, 60) == good
    assert choose_safe_recalled_move(memory, {bad: 48, good: 60}, 60) == bad
    assert choose_safe_recalled_move(memory, {bad: -29999, good: -29995}, -29995) is None
    assert choose_safe_recalled_move(memory, {bad: 100, good: 29999}, 29999) is None


def test_search_recalled_positions_still_search_not_direct_book(tmp_path):
    from engine.position_memory import build_position_memory
    from scripts.build_book import Candidate
    game = Candidate('Carlsen', {'White':'Magnus Carlsen','Black':'Opp'},
                     ('e2e4','e7e5','g1f3','b8c6'), 'unique-gm', 1.0)
    memory = build_position_memory([game])
    path = tmp_path/'memory.json'
    path.write_text(json.dumps(memory))
    bot = Engine(book_path=tmp_path/'no-book.json', memory_path=path)
    result = bot.search(chess.Board(), depth=1, time_limit=None)
    assert result.depth == 1 and not result.book
    assert result.move in chess.Board().legal_moves
    bot.new_game()
    assert bot._memory is None


def test_memory_builder_rejects_duplicate_games_and_illegal_moves():
    from engine.position_memory import build_position_memory
    from scripts.build_book import Candidate
    one = Candidate('Tal', {'White':'Tal', 'Black':'Other'}, ('e2e4',), 'fingerprint', 1.0)
    with pytest.raises(ValueError, match='Duplicate'):
        build_position_memory([one, one])
    bad = Candidate('Tal', {'White':'Tal','Black':'Other'}, ('e2e5',), 'bad', 1.0)
    with pytest.raises(ValueError, match='Illegal'):
        build_position_memory([bad])
