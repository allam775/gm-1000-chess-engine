"""GM-1000 v0.6/v0.7 independent paired Stockfish Skill 5 validation.

Five isolated shards, each with 10 unique paired openings and both colors for
both engines: 5 x 10 x 2 colors x 2 versions = 200 games. Stable source hashes
are compiled in CI; no historical memory, book-move overlay or auto promotion.
Record every game, including invalid/incomplete results without inventing draws.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from scripts.stockfish19_selfplay400 import varied_opening_positions

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = '0d5568e39c643a657d669b320e9463359bab06be'
CANDIDATE_SHA = '26cdee9b59641a24be88a8574418d9d12e25c3e0'
SEED = 26103182
SHARDS = 5
OPENINGS_PER_SHARD = 10
SECONDS = .2
MAX_PLIES = 360


def read_openings():
    book = json.loads((ROOT / 'data/opening_book.json').read_text(encoding='utf-8'))
    seeds = varied_opening_positions(book, pairs=SHARDS * OPENINGS_PER_SHARD, seed=SEED)
    assert len(seeds) == 50
    assert len({chess.Board(x['fen']).epd() for x in seeds}) == len(seeds)
    return seeds


def outcome_label(result: str, color: str) -> str:
    if result == '1/2-1/2':
        return 'draw'
    if result == '*':
        return 'incomplete'
    if result not in ('1-0', '0-1'):
        raise ValueError(f'Unexpected result {result!r}')
    return 'win' if (result == '1-0') == (color == 'white') else 'loss'


def summarize(games: list[dict]) -> dict:
    counts = Counter(g['outcome'] for g in games)
    done = counts['win'] + counts['draw'] + counts['loss']
    by_color = {}
    for color in ('white', 'black'):
        sample = [g for g in games if g['color'] == color]
        col_counts = Counter(g['outcome'] for g in sample)
        completed = col_counts['win'] + col_counts['draw'] + col_counts['loss']
        by_color[color] = {'games': len(sample), 'completed': completed,
                           'wins': col_counts['win'], 'draws': col_counts['draw'],
                           'losses': col_counts['loss'], 'errors': col_counts['error'],
                           'incomplete': col_counts['incomplete'],
                           'score_percent': round(100 * (col_counts['win'] + col_counts['draw'] / 2) / completed, 2)
                           if completed else None}
    return {'games': len(games), 'completed': done,
            'wins': counts['win'], 'draws': counts['draw'], 'losses': counts['loss'],
            'errors': counts['error'], 'incomplete': counts['incomplete'],
            'score_percent': round(100 * (counts['win'] + counts['draw'] / 2) / done, 2)
            if done else None, 'by_color': by_color}


def game_score(row):
    return {'win': 1., 'draw': .5, 'loss': 0.}[row['outcome']]


def run_shard(args):
    if not 0 <= args.shard < SHARDS:
        raise ValueError('shard must be 0..4')
    if not args.v06.is_file() or not args.v07.is_file() or not args.stockfish.is_file():
        raise FileNotFoundError('Missing one or more pinned engine executables')
    seeds = read_openings()
    selected = seeds[args.shard * OPENINGS_PER_SHARD:(args.shard + 1) * OPENINGS_PER_SHARD]
    out = args.out / f'shard-{args.shard}'
    out.mkdir(parents=True, exist_ok=True)
    games = []
    pgn_path = out / 'all-games.pgn'
    binaries = {'v06': args.v06.resolve(), 'v07': args.v07.resolve()}
    config = {'Skill Level': 5, 'Threads': 1, 'Hash': 16}
    with chess.engine.SimpleEngine.popen_uci(str(binaries['v06']), timeout=20) as v06, \
         chess.engine.SimpleEngine.popen_uci(str(binaries['v07']), timeout=20) as v07, \
         chess.engine.SimpleEngine.popen_uci(str(args.stockfish.resolve()), timeout=20) as sf, \
         pgn_path.open('w', encoding='utf-8') as pgn:
        sf.configure({k: v for k, v in {**config, 'UCI_LimitStrength': False}.items()
                      if k in sf.options})
        engines = {'v06': v06, 'v07': v07}
        for offset, opening in enumerate(selected):
            opening_id = args.shard * OPENINGS_PER_SHARD + offset
            for color in ('white', 'black'):
                gm_color = chess.WHITE if color == 'white' else chess.BLACK
                for variant in ('v06', 'v07'):
                    board = chess.Board(opening['fen'])
                    game = chess.pgn.Game()
                    game.setup(board)
                    game.headers.update({
                        'Event': 'GM-1000 native v06 vs v07; independent Skill5 A/B',
                        'White': f'GM1000-{variant}' if gm_color else 'StockfishSkill5',
                        'Black': 'StockfishSkill5' if gm_color else f'GM1000-{variant}',
                        'OpeningPair': str(opening_id), 'Shard': str(args.shard),
                        'EngineVersion': variant, 'OpeningSeed': str(SEED),
                        'GMTimeSeconds': str(SECONDS), 'OpponentTimeSeconds': str(SECONDS),
                        'OpponentSkill': '5', 'GameCapPlies': str(MAX_PLIES),
                        'GMSourceSHA': BASE_SHA if variant == 'v06' else CANDIDATE_SHA,
                        'Memories': 'disabled',
                    })
                    node = game
                    error = None
                    gm = engines[variant]
                    new_game_token = object()
                    opponent_token = object()
                    for ply in range(MAX_PLIES):
                        if board.is_game_over(claim_draw=True):
                            break
                        actor = gm if board.turn == gm_color else sf
                        try:
                            answer = actor.play(board, chess.engine.Limit(time=SECONDS),
                                                game=new_game_token if actor is gm else opponent_token)
                            if answer.move not in board.legal_moves:
                                raise RuntimeError('Invalid or missing move from UCI engine')
                            node = node.add_variation(answer.move)
                            board.push(answer.move)
                        except Exception as exc:
                            error = f'{type(exc).__name__}: {exc}'
                            break
                    actual = board.outcome(claim_draw=True)
                    result = '*' if error or actual is None else actual.result()
                    label = 'error' if error else outcome_label(result, color)
                    game.headers['Result'] = result
                    game.headers['Termination'] = ('engine_error' if error else
                        actual.termination.name if actual else 'move_cap_incomplete')
                    pgn.write(str(game) + '\n\n')
                    pgn.flush()
                    row = {
                        'shard': args.shard, 'opening_id': opening_id,
                        'variant': variant, 'color': color, 'outcome': label,
                        'result': result, 'plies_after_seed': len(list(game.mainline_moves())),
                        'termination': game.headers['Termination'], 'error': error,
                    }
                    games.append(row)
                    # Flush recoverable evidence during tournament, not only on success.
                    (out / 'progress.json').write_text(json.dumps({
                        'schema': 1, 'shard': args.shard, 'played': len(games),
                        'total': 4 * OPENINGS_PER_SHARD,
                        'scores': {v: summarize([g for g in games if g['variant'] == v]) for v in binaries},
                        'games': games}, indent=2) + '\n', encoding='utf-8')
                    print('GM1000_SKILL5_200', args.shard, len(games), '/', 40,
                          variant, color, label, flush=True)
    report = {
        'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'shard': args.shard, 'total_shards': SHARDS,
        'opening_seed': SEED, 'opening_ids': list(range(args.shard * OPENINGS_PER_SHARD,
                                                  (args.shard + 1) * OPENINGS_PER_SHARD)),
        'opening_fens': [x['fen'] for x in selected], 'baseline_sha': BASE_SHA,
        'candidate_sha': CANDIDATE_SHA, 'seconds_per_move': SECONDS,
        'max_plies_after_seed': MAX_PLIES, 'stockfish_level': 5,
        'games': games,
        'scores': {v: summarize([g for g in games if g['variant'] == v]) for v in binaries},
        'pgn_sha256': hashlib.sha256(pgn_path.read_bytes()).hexdigest(),
        'limitations': 'Different GM search cores but same evaluator; Skill Level 5 is not a calibrated Elo rating; time-limited stochastic tournament.'
    }
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    assert len(games) == 40
    if any(x['outcome'] not in ('win', 'draw', 'loss') for x in games):
        raise RuntimeError('One or more games failed to finish; see PGN and progress.json')
    print('SHARD_COMPLETE', args.shard, json.dumps(report['scores']), flush=True)


def aggregate(args):
    reports = []
    for shard in range(SHARDS):
        file = args.input / f'gm1000-skill5-200-shard-{shard}' / 'summary.json'
        if not file.is_file():
            raise FileNotFoundError(f'Missing shard summary {shard}: {file}')
        reports.append(json.loads(file.read_text(encoding='utf-8')))
    assert all(r['shard'] == i and r['opening_seed'] == SEED and
               r['baseline_sha'] == BASE_SHA and r['candidate_sha'] == CANDIDATE_SHA and
               r['stockfish_level'] == 5 and r['seconds_per_move'] == SECONDS
               for i, r in enumerate(reports)), 'Mismatched tournament configuration'
    games = [g for r in reports for g in r['games']]
    assert len(games) == 200, f'Expected 200 games; found {len(games)}'
    keys = [(g['opening_id'], g['color'], g['variant']) for g in games]
    assert len(set(keys)) == 200, 'Duplicate positions or color/version slots'
    assert all(g['outcome'] in ('win', 'draw', 'loss') for g in games), 'Unfinished games cannot be scored'
    assert set(g['opening_id'] for g in games) == set(range(50)), 'Missing opening pair'
    scores = {v: summarize([g for g in games if g['variant'] == v]) for v in ('v06','v07')}
    assert all(x['completed'] == 100 and x['errors'] == 0 and x['incomplete'] == 0
               for x in scores.values())
    by_key = {(g['opening_id'], g['color'], g['variant']): g for g in games}
    paired = [game_score(by_key[(i, color, 'v07')]) - game_score(by_key[(i, color, 'v06')])
              for i in range(50) for color in ('white', 'black')]
    mean_delta = statistics.mean(paired)
    ci = 1.96 * statistics.stdev(paired) / len(paired)**.5
    summary = {
        'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'experiment': 'Frozen v06 vs candidate v07 against Stockfish Skill5, paired independent opening positions',
        'baseline_sha': BASE_SHA, 'candidate_sha': CANDIDATE_SHA,
        'opening_seed': SEED, 'openings': 50, 'colors_per_opening': 2,
        'games_per_version': 100, 'total_games': 200, 'shards': SHARDS,
        'seconds_per_move': SECONDS, 'max_plies_after_seed': MAX_PLIES,
        'stockfish_skill': 5, 'stockfish_threads': 1, 'stockfish_hash_mb': 16,
        'memory_enabled': False, 'learned_eval_enabled': False,
        'scores': scores,
        'paired_score_difference_v07_minus_v06_pct': round(mean_delta * 100, 2),
        'paired_approx_95pct_ci_for_difference_pct': [round((mean_delta-ci)*100,2), round((mean_delta+ci)*100,2)],
        'shard_scorecards': [{'shard': r['shard'], 'scores': r['scores'],
                              'pgn_sha256': r['pgn_sha256']} for r in reports],
        'games': games,
        'limitations': ['Engine strength is assessed against one stochastic skill-level opponent; not calibrated Elo.',
                        '95% normal CI is an approximate descriptive interval over paired slots; shared openings and game dependence limit inference.',
                        'Shards run on separate but nominally equivalent CI machines. No automatic promotion.']
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print('GM1000_SKILL5_200_FINAL', json.dumps({k: v for k, v in summary.items() if k!='games'}, indent=2), flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    shard=sub.add_parser('shard')
    shard.add_argument('--shard', type=int, required=True)
    shard.add_argument('--v06', type=Path, default=ROOT/'build/tournament/v06')
    shard.add_argument('--v07', type=Path, default=ROOT/'build/tournament/v07')
    shard.add_argument('--stockfish', type=Path, default=Path(os.environ.get('STOCKFISH_PATH','/usr/games/stockfish')))
    shard.add_argument('--out', type=Path, default=ROOT/'reports/skill5-200')
    final=sub.add_parser('aggregate')
    final.add_argument('--input', type=Path, default=ROOT/'reports/skill5-200-downloaded')
    final.add_argument('--output', type=Path, default=ROOT/'reports/skill5-200-final/summary.json')
    args=p.parse_args()
    (run_shard if args.command=='shard' else aggregate)(args)


if __name__=='__main__':
    main()