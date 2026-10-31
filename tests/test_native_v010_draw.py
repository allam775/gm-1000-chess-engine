"""Regression: twofold repetition is not automatically a draw."""
import subprocess
from pathlib import Path
import pytest

ENGINE = Path(__file__).resolve().parents[1] / "native/bin/gm1000-native"

@pytest.mark.parametrize(("cycles", "expected"), [(1, "live"), (2, "draw")])
def test_repetition_threshold(cycles, expected):
    if not ENGINE.exists():
        pytest.skip("native engine not compiled")
    cycle = ["g1f3", "g8f6", "f3g1", "f6g8"]
    answer = subprocess.check_output([str(ENGINE), "--draw-status", *(cycle * cycles)], text=True, timeout=10)
    assert answer.strip() == expected
