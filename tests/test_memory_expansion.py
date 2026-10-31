"""Regression checks for append-only grandmaster position-memory expansion."""
from scripts.expand_position_memory import merge_positions

def test_merge_preserves_old_moves_and_grandmaster_counts():
    old = {"position-1": {"e2e4": {"count": 3, "players": {"Carlsen": 2, "Tal": 1}}}}
    add = {
        "position-1": {
            "e2e4": {"count": 2, "players": {"Carlsen": 1, "Kasparov": 1}},
            "d2d4": {"count": 1, "players": {"Fischer": 1}},
        },
        "position-2": {"g1f3": {"count": 1, "players": {"Anand": 1}}},
    }
    merged = merge_positions(old, add)
    assert merged["position-1"]["e2e4"] == {
        "count": 5, "players": {"Carlsen": 3, "Tal": 1, "Kasparov": 1}}
    assert merged["position-1"]["d2d4"]["count"] == 1
    assert merged["position-2"]["g1f3"]["players"] == {"Anand": 1}
    assert old["position-1"]["e2e4"]["count"] == 3

def test_merge_never_erases_old_entries():
    old = {"x": {"a": {"count": 1, "players": {"Tal": 1}}}}
    result = merge_positions(old, {})
    assert result == old
    assert result is not old
