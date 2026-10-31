"""Regressions for Stockfish Skill-5 tournament setup."""
from scripts.run_stockfish5_four_tournaments import tally, read_memory_snapshots
import pytest

def test_skill5_totals():
    rows = [{"wins": 2, "draws": 1, "losses": 1, "completed_games": 4, "errors": 0, "incomplete": 0},
            {"wins": 1, "draws": 1, "losses": 2, "completed_games": 4, "errors": 0, "incomplete": 0}]
    totals = tally(rows)
    assert totals["wins"] == 3 and totals["draws"] == 2 and totals["losses"] == 3
    assert totals["score_percent"] == 50
    assert totals["tournaments_completed"] == 2

def test_skill5_required_memory_snapshots():
    gm, sf, digests = read_memory_snapshots()
    assert gm["source_games"] == 560
    assert sf["games"] == 400
    assert len(digests) == 2
