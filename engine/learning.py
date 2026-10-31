"""Outcome-based incremental learning: bounded evaluation weights + opening experience.

Learns only from completed GM-1000 vs opponent games (result, positions and moves).
Does NOT copy opponent search decisions or Stockfish evaluations and does not
claim neural-network learning or an Elo improvement.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn

from .search import LEARNABLE_FEATURES, book_key, evaluate_components


def empty_state() -> dict:
    return {'schema': 1, 'epochs': 0, 'games_learned': 0,
            'weights': {name: 1.0 for name in LEARNABLE_FEATURES},
            'opening_moves': {}, 'history': []}


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1:
        raise ValueError('Unsupported learning state format')
    for name in LEARNABLE_FEATURES:
        if name not in data.get('weights', {}):
            raise ValueError('Missing learned evaluation feature: ' + name)
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def train_completed_pgn(path: Path, state: dict, *, learning_rate: float = 0.035) -> dict:
    """Retired v0.1 trainer; preserved for a clear compatibility failure.

    The old method attributed whole-game outcomes to unrelated opening moves,
    without position-specific counterfactuals. It also omitted the derivative
    of its tanh activation. It must never silently train a model again.
    Use scripts/study_gm_games.py for game-disjoint supervised studies instead.
    """
    raise RuntimeError(
        "Legacy game-result learning is retired in GM-1000 v0.2; "
        "use scripts/study_gm_games.py and validate before promotion"
    )
