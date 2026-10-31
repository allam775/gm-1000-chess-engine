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
    """Apply exactly one update after an entire round; no in-round leakage.

    The per-move opening reward is the match result, while each non-material
    evaluation feature receives a bounded Monte Carlo outcome-gradient update.
    This is elementary online learning, not an objective measure of strength.
    """
    if not (0 < learning_rate <= 0.2):
        raise ValueError('learning_rate must be in (0, .2]')
    gradients = {f: 0.0 for f in LEARNABLE_FEATURES}
    valid_games = 0
    samples = 0
    new_visits = 0
    with path.open(encoding='utf-8') as stream:
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors:
                raise ValueError('Malformed PGN found during learning')
            result = game.headers.get('Result')
            if result not in ('1-0', '0-1', '1/2-1/2'):
                continue
            if game.headers.get('White') == 'GM-1000':
                gm_color = chess.WHITE
            elif game.headers.get('Black') == 'GM-1000':
                gm_color = chess.BLACK
            else:
                raise ValueError('PGN lacks GM-1000 player header')
            gm_outcome = (0.0 if result == '1/2-1/2'
                          else 1.0 if (result == '1-0') == gm_color else -1.0)
            # Collect before applying per-game result. By construction, this
            # function is called only after all games in the round finished.
            board = game.board()
            own_ply_count = 0
            for ply, move in enumerate(game.mainline_moves()):
                if board.turn == gm_color:
                    own_ply_count += 1
                    if ply < 24:
                        position = state['opening_moves'].setdefault(book_key(board), {})
                        info = position.setdefault(move.uci(), {'visits': 0, 'reward_sum': 0.0})
                        info['visits'] += 1
                        info['reward_sum'] = round(info['reward_sum'] + gm_outcome, 6)
                        new_visits += 1
                board.push(move)
                if board.turn != gm_color and own_ply_count >= 5 and own_ply_count % 5 == 0:
                    if own_ply_count > 40:
                        continue
                    feats = evaluate_components(board)
                    sign = 1 if gm_color == chess.WHITE else -1
                    predicted_cp = sign * (feats['material'] + sum(feats[k] * state['weights'][k] for k in LEARNABLE_FEATURES))
                    predicted = math.tanh(predicted_cp / 650.0)
                    delta = gm_outcome - predicted
                    for k in LEARNABLE_FEATURES:
                        gradients[k] += delta * max(-1.5, min(1.5, sign * feats[k] / 120.0))
                    samples += 1
            valid_games += 1
    if valid_games == 0:
        raise ValueError('No completed games available for learning')
    previous = dict(state['weights'])
    # Averaging across sampled positions keeps LR independent of game length.
    for k in LEARNABLE_FEATURES:
        step = learning_rate * gradients[k] / max(1, samples)
        state['weights'][k] = round(min(1.6, max(0.4, state['weights'][k] + step)), 6)
    state['games_learned'] += valid_games
    state['epochs'] += 1
    entry = {'epoch': state['epochs'], 'learned_games': valid_games,
             'learning_samples': samples, 'opening_move_observations': new_visits,
             'weights_before': previous, 'weights_after': dict(state['weights']),
             'utc': datetime.now(timezone.utc).isoformat()}
    state['history'].append(entry)
    return entry
