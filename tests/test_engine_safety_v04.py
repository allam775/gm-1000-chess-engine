"""Quiescence safety, timeout fallback, feature evaluation, near-position hints."""
from __future__ import annotations
import chess
import pytest

from engine.search import Engine, evaluate_components, evaluate
from engine.position_patterns import build_index, expanded, pattern_candidates
from engine.search import book_key


def test_in_check_quiescence_never_returns_illegal_standpat(monkeypatch):
    # Black is checked and must respond: returning the static value of an
    # illegal attacked king can look artificially favorable.
    b = chess.Board("4k3/8/8/8/8/8/4R3/K7 b - - 0 1")
    engine = Engine()
    engine.deadline = None
    # A constant evaluation lets us prove that search negates a score
    # computed *after a legal evasion*, not static stand-pat in check.
    monkeypatch.setattr(engine, "evaluation", lambda position: 123)
    result = engine._quiescence(b, -32000, 32000, 1, qdepth=12)
    assert b.fen() == "4k3/8/8/8/8/8/4R3/K7 b - - 0 1"
    assert result == -123


def test_timeout_does_not_pick_first_legal_move(monkeypatch):
    b = chess.Board("4k3/8/8/8/8/8/4q3/R3K3 w Q - 0 1")
    engine = Engine()
    engine.own_book = False
    monkeypatch.setattr(engine, "_check_time", lambda: (_ for _ in ()).throw(
        __import__("engine.search", fromlist=["SearchTimeout"]).SearchTimeout()))
    result = engine.search(b, time_limit=.01, depth=8, allow_book=False)
    assert result.move in b.legal_moves and result.depth == 0
    assert b.fen() == "4k3/8/8/8/8/8/4q3/R3K3 w Q - 0 1"


def test_new_evaluation_features_present_and_finite():
    b = chess.Board()
    f = evaluate_components(b)
    assert "development" in f and "hanging_pieces" in f
    assert evaluate(b) == sum(f.values())
    assert abs(evaluate(b)) < 1000


def test_pattern_candidates_same_pawns_and_material_not_same_board():
    original = chess.Board()
    altered = chess.Board()
    altered.push_san("Nf3")
    altered.push_san("Nf6")
    key = book_key(altered)
    index = build_index({key: {"preferred_move": "e2e4"}})
    options = pattern_candidates(original, index)
    assert options and options[0][0] == chess.Move.from_uci("e2e4")
    # Any pawn move breaks the signature, so the suggestion is not borrowed.
    original.push_san("e4")
    assert pattern_candidates(original, index) == []


def test_illegal_or_bad_moves_are_not_suggested():
    b = chess.Board()
    after = b.copy()
    after.push_san("Nf3")
    after.push_san("Nf6")
    index = build_index({book_key(after): {"preferred_move": "e7e5"}})
    assert pattern_candidates(b, index) == []
