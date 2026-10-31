"""Reproducible, game-disjoint supervised study of titled grandmasters' moves.

Analyzes complete games and learns a candidate static-evaluation model with a
proper pairwise logistic gradient. Neither GM moves nor offline outcomes are
assumed objectively optimal. Never deploys a candidate without playing tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.search import LEARNABLE_FEATURES, evaluate_components
from scripts.build_book import get_source, parse_candidates, select_round_robin

# All eight were titled grandmasters; no pre-FIDE-title-era masters in this sample.
GRANDMASTERS = ('Carlsen', 'Kasparov', 'Fischer', 'Karpov',
                'Anand', 'Tal', 'Botvinnik', 'Alekhine')


@dataclass(frozen=True)
class Sample:
    game_hash: str
    ply: int
    expert: tuple[float, ...]
    alternatives: tuple[tuple[float, ...], ...]
    expert_material: float
    alternative_material: tuple[float, ...]


def choose_games(count: int, cache_dir: Path, source_dir: Path | None) -> list:
    from scripts.build_book import PLAYERS
    if count < 200:
        raise ValueError('GM study requires at least 200 distinct games')
    selected_by = {}
    cap = max(50, (count // len(GRANDMASTERS) + 2) * 3)
    for player in GRANDMASTERS:
        content = get_source(player, source_dir, cache_dir)
        selected_by[player], scanned = parse_candidates(content, player, cap)
        print(f'SOURCE {player}: scanned={scanned} eligible={len(selected_by[player])}', flush=True)
    # select_round_robin uses PLAYERS ordering but all selected records are from GRANDMASTERS.
    result = select_round_robin(selected_by, count)
    if len(result) != count:
        raise RuntimeError(f'Only {len(result)} unique GM games; requested {count}')
    if len({x.fingerprint for x in result}) != count:
        raise AssertionError('The game selection must not contain duplicates')
    return result


def expert_color(game) -> bool:
    source = game.source.lower()
    white = game.headers.get('White', '').lower()
    black = game.headers.get('Black', '').lower()
    if source in white:
        return chess.WHITE
    if source in black:
        return chess.BLACK
    raise ValueError(f'Missing named grandmaster {game.source} in selected PGN headers')


def sample_plys(length: int, color: bool, cap: int = 10) -> list[int]:
    # Game phases sampled beyond the 24-ply historical book, avoiding terminal positions.
    eligible = [p for p in range(24, min(length - 1, 170))
                if (p % 2 == (0 if color == chess.WHITE else 1))]
    if not eligible:
        return []
    if len(eligible) <= cap:
        return eligible
    return sorted({eligible[round(i * (len(eligible) - 1) / (cap - 1))]
                   for i in range(cap)})


def features_after(board: chess.Board, move: chess.Move, sign: int) -> tuple[tuple[float, ...], float]:
    board.push(move)
    try:
        comps = evaluate_components(board)
    finally:
        board.pop()
    return tuple(sign * comps[k] / 100.0 for k in LEARNABLE_FEATURES), sign * comps['material'] / 100.0


def game_samples(game, max_positions: int = 10, hardest: int = 4) -> list[Sample]:
    color = expert_color(game)
    sign = 1 if color == chess.WHITE else -1
    plys = set(sample_plys(len(game.moves), color, cap=max_positions))
    board = chess.Board()
    out = []
    for i, uci in enumerate(game.moves):
        move = chess.Move.from_uci(uci)
        if i in plys and board.turn == color and not board.is_game_over(claim_draw=True):
            legal = list(board.legal_moves)
            if move not in legal:
                raise ValueError('Selected game has illegal move')
            if len(legal) > 1:
                expert, expert_material = features_after(board, move, sign)
                alternatives = []
                for other in legal:
                    if other == move:
                        continue
                    feats, mat = features_after(board, other, sign)
                    # Hard negatives: choices that look attractive to the baseline evaluator.
                    rank = mat + sum(feats)
                    alternatives.append((rank, other.uci(), feats, mat))
                alternatives.sort(key=lambda t: (-t[0], t[1]))
                selected = alternatives[:hardest]
                out.append(Sample(game.fingerprint, i, expert,
                                  tuple(x[2] for x in selected), expert_material,
                                  tuple(x[3] for x in selected)))
        board.push(move)
    return out


def softplus(value: float) -> float:
    return max(0.0, value) + math.log1p(math.exp(-abs(value)))


def sigmoid_minus(value: float) -> float:
    """Stable value of 1/(1+exp(value))."""
    if value >= 0:
        t = math.exp(-value)
        return t / (1 + t)
    t = math.exp(value)
    return 1 / (1 + t)


def assess(samples: list[Sample], weights: dict[str, float]) -> dict:
    if not samples:
        raise ValueError('Zero samples: cannot validate a learned model')
    w = tuple(weights[k] for k in LEARNABLE_FEATURES)
    correct_pairs = 0
    total_pairs = 0
    expert_best = 0
    total_loss = 0.0
    for s in samples:
        exp_score = s.expert_material + sum(x * y for x, y in zip(s.expert, w))
        competitor_scores = [mat + sum(x * y for x, y in zip(feat, w))
                             for feat, mat in zip(s.alternatives, s.alternative_material)]
        expert_best += (exp_score >= max(competitor_scores))
        for score in competitor_scores:
            margin = (exp_score - score) / 2.0
            correct_pairs += margin > 0
            total_pairs += 1
            total_loss += softplus(-margin)
    return {'positions': len(samples), 'comparisons': total_pairs,
            'pairwise_accuracy_pct': round(100 * correct_pairs / total_pairs, 2),
            'top1_pct_against_hard_negatives': round(100 * expert_best / len(samples), 2),
            'mean_pairwise_log_loss': round(total_loss / total_pairs, 6)}


def optimize(samples: list[Sample], *, epochs: int = 8, learning_rate: float = 0.015,
             regularization: float = 0.02, seed: int = 2026) -> tuple[dict, list]:
    """Mini-batch pairwise logistic SGD with correct derivative and L2 shrinkage.

    For expert move E and alternative A: loss = softplus(-(score(E)-score(A))/T).
    d(loss)/dw = -(E_features-A_features)/T * sigmoid(-margin).
    Material is held fixed. Bounded weights and regularization reduce overfit.
    """
    if epochs < 1 or not 0 < learning_rate <= .1:
        raise ValueError('Invalid optimizer arguments')
    rng = random.Random(seed)
    w = [1.0] * len(LEARNABLE_FEATURES)
    history = []
    positions = list(samples)
    for epoch in range(epochs):
        rng.shuffle(positions)
        # Per-position gradients; average over alternative moves, update per 16 positions.
        grads = [0.0] * len(w)
        batch_size = 0
        for s in positions:
            for a, material in zip(s.alternatives, s.alternative_material):
                diff = [(x - y) / 2.0 for x, y in zip(s.expert, a)]
                margin = (s.expert_material - material) / 2.0 + sum(v * z for v, z in zip(diff, w))
                coeff = -sigmoid_minus(margin) / len(s.alternatives)
                for k, val in enumerate(diff):
                    grads[k] += coeff * val
            batch_size += 1
            if batch_size == 16:
                for k in range(len(w)):
                    grad = grads[k] / batch_size + regularization * (w[k] - 1)
                    w[k] = max(.7, min(1.3, w[k] - learning_rate * grad))
                grads = [0.0] * len(w)
                batch_size = 0
        if batch_size:
            for k in range(len(w)):
                grad = grads[k] / batch_size + regularization * (w[k] - 1)
                w[k] = max(.7, min(1.3, w[k] - learning_rate * grad))
        history.append({'epoch': epoch + 1, 'weights':
                        {k: round(value, 6) for k, value in zip(LEARNABLE_FEATURES, w)}})
    return {k: round(value, 6) for k, value in zip(LEARNABLE_FEATURES, w)}, history


def study(args: argparse.Namespace) -> dict:
    if args.games < 200:
        raise ValueError('Minimum 200 distinct grandmaster games required')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = choose_games(args.games, args.cache_dir, args.source_dir)
    rng = random.Random(args.seed)
    # Shuffle game IDs, not position samples, to prevent same-game leakage.
    by_player = {name: [] for name in GRANDMASTERS}
    for game in selected:
        by_player[game.source].append(game)
    train, holdout = [], []
    for player in GRANDMASTERS:
        games = by_player[player]
        rng.shuffle(games)
        split = max(1, round(len(games) * args.holdout_fraction))
        holdout.extend(games[:split])
        train.extend(games[split:])
    train_samples = [s for game in train for s in game_samples(game, args.positions_per_game)]
    test_samples = [s for game in holdout for s in game_samples(game, args.positions_per_game)]
    if not train_samples or not test_samples:
        raise RuntimeError('Not enough GM positions for disjoint train/validation split')
    if set(s.game_hash for s in train_samples) & set(s.game_hash for s in test_samples):
        raise AssertionError('Train and holdout data share games')
    initial = {name: 1.0 for name in LEARNABLE_FEATURES}
    weights, training_history = optimize(train_samples, epochs=args.epochs, seed=args.seed)
    base = assess(test_samples, initial)
    candidate = assess(test_samples, weights)
    # Offline matching of grandmaster moves is only a PROXY; require independent
    # paired chess matches with strength+uncertainty checks before promotion.
    report = {
        'schema': 2, 'utc': datetime.now(timezone.utc).isoformat(),
        'source': 'PGN Mentor titled GM player archives',
        'players': list(GRANDMASTERS), 'selected_unique_games': len(selected),
        'train_games': len(train), 'holdout_games': len(holdout),
        'train_position_samples': len(train_samples), 'holdout_position_samples': len(test_samples),
        'train_game_ids_sha256': hashlib.sha256('\n'.join(sorted(g.fingerprint for g in train)).encode().strip()).hexdigest(),
        'holdout_game_ids_sha256': hashlib.sha256('\n'.join(sorted(g.fingerprint for g in holdout)).encode().strip()).hexdigest(),
        'selection_by_player': dict(sorted(Counter(x.source for x in selected).items())),
        'sampling': 'Up to ten positions per game beyond ply 24; one named grandmaster side per game; 4 highest baseline-ranked legal alternatives per position',
        'training_objective': 'pairwise logistic imitation of played GM move, fixed material, regularized bounded evaluation weights',
        'holdout_control': base, 'holdout_candidate': candidate,
        'offline_validation_gate': {'passes': candidate['pairwise_accuracy_pct'] >= base['pairwise_accuracy_pct'] + 1.0 and candidate['mean_pairwise_log_loss'] < base['mean_pairwise_log_loss'],
                                    'minimum_improvement_pp': 1.0},
        'promotion': 'NOT PROMOTED: offline move imitation alone cannot prove playing strength; a separate paired match evaluation is mandatory',
        'optimizer_epochs': args.epochs, 'weights': weights, 'optimizer_history': training_history,
        'limitations': 'GM-played moves can be suboptimal. One-ply feature imitation is not game-tree search, not Stockfish-supervised and not evidence of higher Elo.'
    }
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    candidate_state = {'schema': 1, 'source': 'GM-1000 v0.2 GM game study, candidate ONLY',
                       'weights': weights, 'opening_moves': {},
                       'epochs': args.epochs, 'games_learned': len(train),
                       'history': [{'source': 'game-disjoint supervised ranking',
                                    'train_games': len(train), 'validation_games': len(holdout),
                                    'validation': candidate}]}
    (args.output_dir / 'candidate.json').write_text(json.dumps(candidate_state, indent=2) + '\n', encoding='utf-8')
    index = [{'sha256': g.fingerprint, 'player': g.source, 'event': g.headers.get('Event'),
              'year': g.headers.get('Date'), 'moves': len(g.moves), 'split':
              'validation' if g in holdout else 'training'} for g in selected]
    (args.output_dir / 'selected_games.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')
    print('GM_STUDY_REPORT', json.dumps({k: v for k, v in report.items() if k not in ('optimizer_history',)}, indent=2), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=200)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--epochs', type=int, default=8)
    parser.add_argument('--positions-per-game', type=int, default=10)
    parser.add_argument('--holdout-fraction', type=float, default=.2)
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'data/cache')
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports/gm-study-v02')
    args = parser.parse_args()
    if not .1 <= args.holdout_fraction <= .4:
        parser.error('holdout-fraction must be between .1 and .4')
    study(args)


if __name__ == '__main__':
    main()
