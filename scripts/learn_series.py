"""Run 20 independent 4-game mini-tournaments, learn after each, evaluate held-out.

Every round uses the preceding round's persisted learning state. All match
conditions are fixed, opponent version is recorded, and learning is never
applied between games inside a mini-tournament.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.learning import load_state, save_state, train_completed_pgn
from scripts.arena import run as arena_run


def run(args: argparse.Namespace) -> dict:
    if not 1 <= args.rounds <= 100 or args.games < 2 or args.games % 2 != 0:
        raise ValueError('Use 1..100 rounds with even games >=2 for balanced colors')
    if not .02 <= args.seconds_per_move <= 2:
        raise ValueError('seconds-per-move must be between .02 and 2')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_file = ROOT / 'data' / 'learning_state.json'
    if args.reset:
        if state_file.exists():
            raise FileExistsError('Refusing to overwrite existing learned state; archive/delete deliberately first')
    state = load_state(state_file)
    stockfish_path = args.stockfish or os.environ.get('STOCKFISH_PATH') or shutil.which('stockfish')
    if not stockfish_path and Path('/usr/games/stockfish').exists():
        stockfish_path = '/usr/games/stockfish'
    if not stockfish_path:
        raise FileNotFoundError('Stockfish not found')
    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as sf:
        stockfish_name = sf.id.get('name', 'Stockfish')
    history = []
    for index in range(1, args.rounds + 1):
        out = args.output_dir / f'round-{index:02d}'
        cfg = SimpleNamespace(games=args.games, stockfish_skill=args.stockfish_skill,
            seconds_per_move=args.seconds_per_move, max_plies=args.max_plies,
            stockfish=stockfish_path, own_book=True, learning=True, output_dir=out)
        summary = arena_run(cfg)
        before = state['epochs']
        update = train_completed_pgn(out / 'matches.pgn', state, learning_rate=args.learning_rate)
        if state['epochs'] != before + 1:
            raise AssertionError('Training must advance exactly once per tournament')
        save_state(state_file, state)  # persisted before next tournament starts
        (out / 'learning_update.json').write_text(json.dumps(update, indent=2) + '\n', encoding='utf-8')
        record = {'round': index, 'epoch': state['epochs'],
                  'wins': summary['wins'], 'draws': summary['draws'],
                  'losses': summary['losses'], 'completed': summary['completed_games'],
                  'errors': summary['errors'], 'incomplete': summary['incomplete'],
                  'score_percent': summary['score_percent'],
                  'training_samples': update['learning_samples'],
                  'opening_observations': update['opening_move_observations']}
        history.append(record)
        (args.output_dir / 'rounds.json').write_text(json.dumps(history, indent=2) + '\n', encoding='utf-8')
        print('LEARNING ROUND', json.dumps(record, sort_keys=True), flush=True)
    def evaluation(name: str, learning: bool) -> dict:
        cfg = SimpleNamespace(games=args.eval_games, stockfish_skill=args.stockfish_skill,
            seconds_per_move=args.seconds_per_move, max_plies=args.max_plies,
            stockfish=stockfish_path, own_book=True, learning=learning,
            output_dir=args.output_dir / name)
        return arena_run(cfg)
    # Holdout comparison: identical colors, engine code, time and opponent.
    # Non-learning control ignores trained experience and feature weights.
    control = evaluation('holdout-control', False)
    trained = evaluation('holdout-trained', True)
    totals = {k: sum(x[k] for x in history) for k in ('wins', 'draws', 'losses', 'completed', 'errors', 'incomplete')}
    report = {'schema': 1, 'utc': datetime.now(timezone.utc).isoformat(),
              'tournaments': len(history), 'games_per_tournament': args.games,
              'opponent': stockfish_name, 'stockfish_skill': args.stockfish_skill,
              'seconds_per_move': args.seconds_per_move, 'total': totals,
              'training_score_percent': round(100*(totals['wins']+.5*totals['draws'])/totals['completed'],2)
                if totals['completed'] else None,
              'initial_epochs': state['epochs'] - len(history),
              'final_epochs': state['epochs'], 'total_games_learned': state['games_learned'],
              'learned_weights': state['weights'], 'holdout_games_per_side': args.eval_games,
              'holdout_control': {k:control[k] for k in ('wins','draws','losses','completed_games','errors','score_percent')},
              'holdout_trained': {k:trained[k] for k in ('wins','draws','losses','completed_games','errors','score_percent')},
              'rounds': history,
              'disclaimer': 'Training games are in-sample; scores are not Elo ratings. ' \
                            'Eight or fewer holdout games per variant are statistically inconclusive.'}
    (args.output_dir / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    with (args.output_dir / 'rounds.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    print('FINAL SUMMARY', json.dumps({k:v for k,v in report.items() if k!='rounds'}, indent=2), flush=True)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rounds', type=int, default=20)
    p.add_argument('--games', type=int, default=4)
    p.add_argument('--eval-games', type=int, default=8)
    p.add_argument('--stockfish-skill', type=int, default=0)
    p.add_argument('--seconds-per-move', type=float, default=.1)
    p.add_argument('--learning-rate', type=float, default=.035)
    p.add_argument('--max-plies', type=int, default=260)
    p.add_argument('--stockfish', default=None)
    p.add_argument('--reset', action='store_true', default=False)
    p.add_argument('--output-dir', type=Path, default=ROOT / 'reports' / 'learning-series')
    a = p.parse_args()
    if a.eval_games < 2 or a.eval_games % 2:
        p.error('eval-games must be even and >=2')
    run(a)


if __name__ == '__main__':
    main()
