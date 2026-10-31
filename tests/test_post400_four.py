"""Regression checks for independent Stockfish-memory comparison."""
from pathlib import Path
from engine.uci import UCI
import json
import chess

ROOT = Path(__file__).resolve().parents[1]

def test_stockfish_memory_toggle_is_independent():
    ui = UCI()
    assert ui.engine.memory_enabled and ui.engine.stockfish_memory_enabled
    ui.process('setoption name StockfishMemory value false')
    assert ui.engine.memory_enabled and not ui.engine.stockfish_memory_enabled
    ui.process('setoption name StockfishMemory value true')
    assert ui.engine.memory_enabled and ui.engine.stockfish_memory_enabled

def test_saved_stockfish_overlay_and_gm_base_are_distinct():
    gm = json.loads((ROOT/'data/position_memory_report.json').read_text())
    sf = json.loads((ROOT/'data/stockfish19_position_memory_report.json').read_text())
    assert gm['source_games'] == 560
    assert sf['engine_version'] == 'Stockfish 19'
    assert sf['stockfish_skill'] == 20 and sf['games'] == 400
    assert sf['original_gm_memory_unchanged'] is True
