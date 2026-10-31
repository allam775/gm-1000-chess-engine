"""Run a deterministic-color, fixed-time head-to-head GM-1000 vs Stockfish."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]


def run(args: argparse.Namespace) -> dict:
    stockfish_path = args.stockfish or os.environ.get('STOCKFISH_PATH') or shutil.which('stockfish')
    if not stockfish_path and Path('/usr/games/stockfish').exists():
        stockfish_path = '/usr/games/stockfish'
    if not stockfish_path:
        raise FileNotFoundError('Stockfish not found. Install stockfish or set STOCKFISH_PATH.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    results = []
    # Starting-position book may be absent: testing remains meaningful without it.
    with chess.engine.SimpleEngine.popen_uci([sys.executable, '-u', '-m', 'engine.uci'], cwd=str(ROOT)) as gm, \
            chess.engine.SimpleEngine.popen_uci(stockfish_path) as stockfish:
        if 'Skill Level' not in stockfish.options:
            raise RuntimeError('Installed Stockfish does not support Skill Level')
        stockfish.configure({'Skill Level': args.stockfish_skill, 'Threads': 1, 'Hash': 16})
        with (args.output_dir / 'matches.pgn').open('w', encoding='utf-8') as stream:
            for index in range(args.games):
                board = chess.Board()
                game = chess.pgn.Game()
                game.headers['Event'] = 'GM-1000 Baseline Arena'
                game.headers['Round'] = str(index + 1)
                gm_color = chess.WHITE if index % 2 == 0 else chess.BLACK
                game.headers['White'] = 'GM-1000' if gm_color else 'Stockfish'
                game.headers['Black'] = 'Stockfish' if gm_color else 'GM-1000'
                game.headers['GM1000Version'] = '0.3-position-memory'
                game.headers['StockfishSkill'] = str(args.stockfish_skill)
                game.headers['PositionMemory'] = 'enabled' if getattr(args, 'position_memory', True) else 'disabled'
                game.headers['SecondsPerMove'] = str(args.seconds_per_move)
                gm.configure({'OwnBook': args.own_book,
                              'Learning': getattr(args, 'learning', True),
                              'PositionMemory': getattr(args, 'position_memory', True)})
                game_token = object()  # python-chess sends ucinewgame on token change.
                node = game
                errors = []
                for ply in range(args.max_plies):
                    if board.is_game_over(claim_draw=True):
                        break
                    player = gm if board.turn == gm_color else stockfish
                    engine_name = 'GM-1000' if player is gm else 'Stockfish'
                    try:
                        reply = player.play(board, chess.engine.Limit(time=args.seconds_per_move),
                                            game=game_token)
                        move = reply.move
                        if move is None or move not in board.legal_moves:
                            raise ValueError(f'engine returned illegal move: {move}')
                        node = node.add_variation(move)
                        board.push(move)
                    except Exception as exc:
                        errors.append(f'{engine_name} at ply {ply + 1}: {type(exc).__name__}: {exc}')
                        break
                outcome = board.outcome(claim_draw=True)
                if errors:
                    counts['errors'] += 1
                    # Aborted games are not silently scored as wins/losses.
                    result = '*'
                    termination = 'engine_error'
                elif outcome:
                    result = outcome.result()
                    termination = outcome.termination.name
                    counts['completed'] += 1
                    if outcome.winner is None:
                        counts['draws'] += 1
                    elif outcome.winner == gm_color:
                        counts['wins'] += 1
                    else:
                        counts['losses'] += 1
                else:
                    result = '*'
                    termination = 'move_cap_incomplete'
                    counts['incomplete'] += 1
                game.headers['Result'] = result
                game.headers['Termination'] = termination
                stream.write(str(game) + '\n\n')
                item = {'game': index + 1, 'gm_color': 'white' if gm_color else 'black',
                        'result': result, 'plies': board.ply(), 'termination': termination,
                        'errors': errors}
                results.append(item)
                print(f'Game {index+1}/{args.games}: {result} ({termination}, {board.ply()} plies)', flush=True)
    completed = counts['completed']
    summary = {
        'engine': 'GM-1000 0.1', 'opponent': 'Stockfish',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'config': {'games': args.games, 'stockfish_skill': args.stockfish_skill,
                   'seconds_per_move': args.seconds_per_move,
                   'max_plies': args.max_plies, 'own_book': args.own_book,
                   'position_memory': getattr(args, 'position_memory', True)},
        'completed_games': completed, 'wins': counts['wins'], 'draws': counts['draws'],
        'losses': counts['losses'], 'errors': counts['errors'],
        'incomplete': counts['incomplete'],
        'score_percent': round(100 * (counts['wins'] + .5 * counts['draws']) / completed, 2)
                         if completed else None,
        'games': results,
    }
    (args.output_dir / 'results.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=4)
    parser.add_argument('--stockfish-skill', type=int, default=0)
    parser.add_argument('--seconds-per-move', type=float, default=.2)
    parser.add_argument('--max-plies', type=int, default=300)
    parser.add_argument('--stockfish', default=None)
    parser.add_argument('--own-book', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--learning', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--position-memory', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    if not 0 <= args.stockfish_skill <= 20:
        parser.error('stockfish-skill must be 0..20')
    if args.games < 1 or args.seconds_per_move < .02 or args.max_plies < 1:
        parser.error('games>=1, seconds-per-move>=.02, max-plies>=1 required')
    print(json.dumps(run(args), indent=2))


if __name__ == '__main__':
    main()
