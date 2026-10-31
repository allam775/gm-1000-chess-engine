"""Create 400 NEW Stockfish 19 Skill 20 self-play games from varied openings.

This is not a database of externally published games. The two opponents are
separate Stockfish 19 UCI processes at the same maximum skill setting. Games
are saved as PGN with both opening FEN and engine version, including incomplete
ones as '*' rather than inventing winners. The original GM memory is untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engine.search import book_key


def varied_opening_positions(book: dict, *, pairs: int = 200, seed: int = 2026) -> list[dict]:
    """Sample distinct legal opening FENs from the 1,000-game book graph."""
    rng = random.Random(seed)
    positions = book['positions']
    seen = set()
    selected = []
    for _ in range(100000):
        if len(selected) >= pairs:
            break
        board = chess.Board()
        target = rng.choice((8, 10, 12, 14, 16, 18, 20))
        for ply in range(target):
            options = positions.get(book_key(board), {})
            legal = []
            for uci, count in options.items():
                try:
                    move = chess.Move.from_uci(uci)
                    if move in board.legal_moves:
                        legal.append((move, max(1, int(count)) ** 0.5))
                except (TypeError, ValueError):
                    pass
            if not legal:
                break
            move = rng.choices([x[0] for x in legal], weights=[x[1] for x in legal], k=1)[0]
            board.push(move)
        if len(board.move_stack) < 8 or board.is_game_over():
            continue
        key = book_key(board)
        if key in seen:
            continue
        seen.add(key)
        selected.append({'fen': board.fen(), 'epd': key, 'opening_plies': board.ply()})
    if len(selected) != pairs:
        raise RuntimeError(f'Only {len(selected)} distinct opening seeds; need {pairs}')
    return selected


def run(args):
    if args.games != 400 or args.skill != 20:
        raise ValueError('This audited experiment requires exactly 400 games at Skill Level 20')
    if not .01 <= args.move_time <= 1.0 or not 80 <= args.max_plies <= 500:
        raise ValueError('Invalid time per move or maximum plies')
    path = Path(args.stockfish or os.environ.get('STOCKFISH_PATH', ''))
    if not path.is_file():
        raise FileNotFoundError('Pass the pinned official Stockfish 19 executable')
    args.out.mkdir(parents=True, exist_ok=True)
    book = json.loads((ROOT/'data/opening_book.json').read_text(encoding='utf-8'))
    if book.get('selected_games') != 1000:
        raise AssertionError('Expected verified original 1000-game opening book')
    seeds = varied_opening_positions(book, pairs=args.games//2, seed=args.seed)
    (args.out/'opening_seeds.json').write_text(json.dumps(seeds, indent=2)+'\n', encoding='utf-8')
    games, counts = [], Counter()
    pgn_path = args.out/'matches.pgn'
    with chess.engine.SimpleEngine.popen_uci(str(path)) as a, \
         chess.engine.SimpleEngine.popen_uci(str(path)) as b:
        name_a, name_b = a.id.get('name', ''), b.id.get('name', '')
        if 'Stockfish 19' not in name_a or 'Stockfish 19' not in name_b:
            raise RuntimeError(f'Wrong Stockfish release: {name_a} / {name_b}')
        for engine in (a, b):
            if 'Skill Level' not in engine.options:
                raise RuntimeError('Official release lacks Skill Level UCI option')
            cfg = {'Skill Level': 20, 'Threads': 1, 'Hash': 32}
            if 'UCI_LimitStrength' in engine.options:
                cfg['UCI_LimitStrength'] = False
            engine.configure(cfg)
        with pgn_path.open('w', encoding='utf-8') as stream:
            for i in range(args.games):
                seed = seeds[i//2]
                board = chess.Board(seed['fen'])
                game = chess.pgn.Game()
                game.setup(board)
                game.headers.update({'Event': 'GM-1000 Stockfish 19 maximum-skill study',
                    'White': name_a if i % 2 == 0 else name_b,
                    'Black': name_b if i % 2 == 0 else name_a,
                    'Round': str(i+1), 'Pair': str(i//2+1),
                    'SkillLevel': '20', 'MoveTimeSeconds': str(args.move_time),
                    'Source': 'new Stockfish 19 self-play'})
                node = game
                failure = None
                for ply in range(args.max_plies):
                    if board.is_game_over(claim_draw=True):
                        break
                    mover = (a if board.turn == chess.WHITE else b) if i % 2 == 0 else (b if board.turn == chess.WHITE else a)
                    try:
                        reply = mover.play(board, chess.engine.Limit(time=args.move_time), game=(i//2, i))
                        move = reply.move
                        if move is None or move not in board.legal_moves:
                            raise RuntimeError('Illegal or missing Stockfish move')
                        node = node.add_variation(move)
                        board.push(move)
                    except Exception as exc:
                        failure = f'{type(exc).__name__}: {exc}'
                        break
                outcome = board.outcome(claim_draw=True)
                if failure:
                    game.headers['Result'] = '*'
                    game.headers['Termination'] = 'engine_error'
                    counts['errors'] += 1
                elif outcome:
                    game.headers['Result'] = outcome.result()
                    game.headers['Termination'] = outcome.termination.name
                    counts['completed'] += 1
                    if outcome.winner is None:
                        counts['draws'] += 1
                    else:
                        counts['decisive'] += 1
                else:
                    game.headers['Result'] = '*'
                    game.headers['Termination'] = 'move_cap_incomplete'
                    counts['incomplete'] += 1
                stream.write(str(game)+'\n\n')
                stream.flush()
                record = {'game': i+1, 'pair': i//2+1, 'result':game.headers['Result'],
                          'termination':game.headers['Termination'],
                          'played_plies': len(board.move_stack),
                          'error':failure}
                games.append(record)
                if (i+1)%10 == 0:
                    (args.out/'progress.json').write_text(json.dumps({'games':len(games), 'counts':dict(counts),
                        'recent':games[-10:]},indent=2)+'\n',encoding='utf-8')
                    print('STOCKFISH19_PROGRESS', i+1, '/', args.games, dict(counts), flush=True)
    report = {'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
        'stockfish':name_a,'skill_level':20, 'games_requested':args.games,
        'games_recorded':len(games),'opening_pairs':len(seeds),
        'seconds_per_move':args.move_time,'max_plies':args.max_plies,
        'completed':counts['completed'],'draws':counts['draws'],
        'decisive':counts['decisive'],'incomplete':counts['incomplete'],'errors':counts['errors'],
        'opening_seed_sha256':hashlib.sha256((args.out/'opening_seeds.json').read_bytes()).hexdigest(),
        'pgn_sha256':hashlib.sha256(pgn_path.read_bytes()).hexdigest(),
        'scope':'400 newly generated Stockfish 19 Skill 20 self-play games, not an externally published latest-400 archive',
        'games':games}
    (args.out/'games_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if len(games)!=400 or counts['errors']:
        raise RuntimeError(f'Incomplete run or engine failures: {dict(counts)}')
    print('FINISHED_400_GAMES',json.dumps({k:v for k,v in report.items() if k!='games'}),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--games',type=int,default=400)
    p.add_argument('--skill',type=int,default=20)
    p.add_argument('--move-time',type=float,default=.025)
    p.add_argument('--max-plies',type=int,default=240)
    p.add_argument('--seed',type=int,default=20261031)
    p.add_argument('--stockfish',default=None)
    p.add_argument('--out',type=Path,default=ROOT/'reports/stockfish19-skill20-400')
    run(p.parse_args())


if __name__=='__main__':
    main()
