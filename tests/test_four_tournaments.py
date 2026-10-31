"""Check that tournament toggles reach the real UCI engine without modifying memory."""
from pathlib import Path
from engine.uci import UCI
from engine.search import Engine

def test_uci_position_memory_switch():
    u = UCI()
    assert u.engine.memory_enabled is True
    u.process("setoption name PositionMemory value false")
    assert u.engine.memory_enabled is False
    u.process("setoption name PositionMemory value true")
    assert u.engine.memory_enabled is True

def test_reported_memory_exists():
    p = Path(__file__).resolve().parents[1]/"data"/"position_memory.json"
    assert p.exists()
    from json import loads
    memory = loads(p.read_text(encoding="utf-8"))
    assert memory["source_games"] == 560
    assert memory["positions_count"] >= 32233
