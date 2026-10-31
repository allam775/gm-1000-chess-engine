"""Persist 200-GM study's TRAINING positions so GM-1000 can recall them.

Retrieves the exact eight titled-GM source archives with the v0.2 study's
selection seed and 160/40 split, and verifies both partitions against the
published study's SHA-256 game ID digest. Validation games are never memorized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.position_memory import build_position_memory
from scripts.study_gm_games import GRANDMASTERS, choose_games


def digest(games) -> str:
    return hashlib.sha256('\n'.join(sorted(g.fingerprint for g in games)).encode().strip()).hexdigest()


def run(args) -> dict:
    study = json.loads(args.study_report.read_text(encoding='utf-8'))
    if study['selected_unique_games'] < 200 or args.games != study['selected_unique_games']:
        raise ValueError('Selected study/report must agree and contain >=200 games')
    games = choose_games(args.games, args.cache_dir, args.source_dir)
    buckets = {player: [] for player in GRANDMASTERS}
    for game in games:
        buckets[game.source].append(game)
    rng = random.Random(args.seed)
    train, validation = [], []
    for player in GRANDMASTERS:
        pool = buckets[player]
        rng.shuffle(pool)
        split = max(1, round(len(pool) * args.holdout_fraction))
        validation.extend(pool[:split])
        train.extend(pool[split:])
    if len(train) != study['train_games'] or len(validation) != study['holdout_games']:
        raise AssertionError('Training and validation partition counts differ from v0.2 study')
    if digest(train) != study['train_game_ids_sha256'] or digest(validation) != study['holdout_game_ids_sha256']:
        raise AssertionError('Study game IDs differ; refusing to leak validation games into position memory')
    data = build_position_memory(train, max_plies=args.max_plies)
    data['training_games_sha256'] = digest(train)
    data['validation_games_sha256'] = digest(validation)
    data['holdout_games_excluded'] = len(validation)
    data['players'] = list(GRANDMASTERS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    report = {key: data[key] for key in ('schema', 'source', 'source_games', 'max_plies',
        'positions_count', 'move_pairs_count', 'observations', 'holdout_games_excluded',
        'training_games_sha256', 'validation_games_sha256', 'players')}
    report['lookup'] = 'Exact EPD key; named-GM moves only; count-weighted bounded search preference'
    report['safety'] = 'Legal moves only; compare with alpha-beta search, prefer memory only within 20 centipawns of searched best score; no automatic candidate weight approval'
    report['limitation'] = 'Recorded GM move is not necessarily best; these are remembered positions, not chess Elo gains or neural network training.'
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('POSITION_MEMORY', json.dumps(report, indent=2), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--games', type=int, default=200)
    p.add_argument('--seed', type=int, default=2026)
    p.add_argument('--holdout-fraction', type=float, default=.2)
    p.add_argument('--max-plies', type=int, default=180)
    p.add_argument('--cache-dir', type=Path, default=ROOT / 'data/cache')
    p.add_argument('--source-dir', type=Path, default=None)
    p.add_argument('--study-report', type=Path, default=ROOT / 'data/gm_study_report_v02.json')
    p.add_argument('--output', type=Path, default=ROOT / 'data/position_memory.json')
    p.add_argument('--report-output', type=Path, default=ROOT / 'data/position_memory_report.json')
    args = p.parse_args()
    if not .1 <= args.holdout_fraction <= .4 or args.max_plies < 2:
        p.error('invalid split fraction or max plies')
    run(args)


if __name__ == '__main__':
    main()
