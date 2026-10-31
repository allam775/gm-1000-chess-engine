"""Forensic audit of the 16 archived Skill-5 arena games with Stockfish 19.

This is independent *post-game* analysis. We NEVER use Stockfish guidance to
rewrite GM-1000 weights/memory without later holdout evaluation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engine.search import book_key


def phase(ply: int) -> str:
    return 'opening' if ply <= 20 else 'middlegame' if ply <= 60 else 'late'


def mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def describe_group(games: list[dict], color: str | None = None) -> dict:
    included = [g for g in games if color is None or g['gm_color'] == color]
    gm_moves = [m for game in included for m in game['moves'] if m['side'] == 'gm' and m['cp_loss'] is not None]
    opp_moves = [m for game in included for m in game['moves'] if m['side'] == 'opponent' and m['cp_loss'] is not None]
    def stats(moves):
        return {
            'moves_analyzed': len(moves),
            'mean_cp_loss': mean([m['cp_loss'] for m in moves]),
            'median_cp_loss': round(statistics.median([m['cp_loss'] for m in moves]), 1) if moves else None,
            'inaccuracies_100cp': sum(m['cp_loss'] >= 100 for m in moves),
            'mistakes_200cp': sum(m['cp_loss'] >= 200 for m in moves),
            'severe_300cp': sum(m['cp_loss'] >= 300 for m in moves),
            'by_phase': {
                stage: {'moves': len(sub := [m for m in moves if m['phase'] == stage]),
                        'mean_cp_loss': mean([m['cp_loss'] for m in sub]),
                        'mistakes_200cp': sum(m['cp_loss'] >= 200 for m in sub)}
                for stage in ('opening', 'middlegame', 'late')
            }
        }
    gm_all = [m for game in included for m in game['moves'] if m['side'] == 'gm']
    mem = {
        'gm_moves_total': len(gm_all),
        'gm_exact_positions_seen': sum(m['in_gm_memory'] for m in gm_all),
        'stockfish19_exact_positions_seen': sum(m['in_sf_memory'] for m in gm_all),
        'gm_memory_top_move_followed': sum(m['followed_gm_top'] for m in gm_all),
        'sf_overlay_preferred_move_followed': sum(m['followed_sf_preferred'] for m in gm_all),
        'sf_overlay_preferred_move_disagreed': sum(m['in_sf_memory'] and not m['followed_sf_preferred'] for m in gm_all),
    }
    return {'games': len(included), 'game_ids': [g['id'] for g in included],
            'gm': stats(gm_moves), 'opponent': stats(opp_moves), 'memory': mem,
            'first_gm_mistake_200cp_mean_ply': mean([g['first_gm_mistake_200cp']['ply'] for g in included if g['first_gm_mistake_200cp']]),
            'games_with_gm_200cp_mistake': sum(bool(g['first_gm_mistake_200cp']) for g in included),
            'mean_length_plies': mean([g['plies'] for g in included])}


def parse_games(source: Path) -> tuple[list[tuple[str, chess.pgn.Game]], dict]:
    archived = []
    hashes = {}
    for number in range(1, 5):
        path = source / f'tournament-{number:02d}' / 'matches.pgn'
        data = path.read_bytes()
        hashes[str(path.relative_to(source))] = hashlib.sha256(data).hexdigest()
        with path.open(encoding='utf-8') as f:
            for index in range(1, 5):
                game = chess.pgn.read_game(f)
                if game is None:
                    raise AssertionError(f'Missing tournament {number}, game {index}')
                if game.errors:
                    raise ValueError(f'PGN errors in T{number}G{index}: {game.errors}')
                expected_color = chess.WHITE if index % 2 else chess.BLACK
                actual_color = chess.WHITE if game.headers['White'] == 'GM-1000' else chess.BLACK
                if expected_color != actual_color:
                    raise AssertionError('Color alternation mismatch')
                if (game.headers.get('PositionMemory') != 'enabled' or
                    game.headers.get('StockfishMemory') != 'enabled' or
                    game.headers.get('StockfishSkill') != '5'):
                    raise AssertionError('Memory configuration or opponent level does not match')
                archived.append((f'T{number}G{index}', game))
            if chess.pgn.read_game(f) is not None:
                raise ValueError(f'Unexpected extra game in {path}')
    if len(archived) != 16:
        raise AssertionError('Expected exactly 16 original games')
    return archived, hashes


def analysis_score(engine, board: chess.Board, seconds: float, *, only_move: chess.Move | None = None):
    """Return centipawn score from the original side-to-move viewpoint.

    Compare best and forced played move at same root, same time budget.
    Mate is capped at +/- 10000cp, and analysis has finite-time uncertainty.
    """
    info = engine.analyse(board, chess.engine.Limit(time=seconds),
                          root_moves=[only_move] if only_move is not None else None)
    score = info.get('score')
    if score is None:
        raise RuntimeError('Stockfish returned no evaluation')
    num = score.pov(board.turn).score(mate_score=10000)
    pv = info.get('pv', [])
    return num, pv[0] if pv else None


def run(args):
    if args.analysis_seconds < .025:
        raise ValueError('Analysis seconds must be >= 0.025 per root')
    archived, sources_sha = parse_games(args.pgn_dir)
    gm_memory = json.loads((ROOT/'data/position_memory.json').read_text(encoding='utf-8'))
    sf_memory = json.loads((ROOT/'data/stockfish19_position_memory.json').read_text(encoding='utf-8'))
    assert gm_memory['source_games'] == 560
    assert sf_memory['games'] == 400 and sf_memory['positions_count'] == 43702
    gm_positions = gm_memory['positions']
    sf_positions = sf_memory['positions']
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    from hashlib import sha256
    with chess.engine.SimpleEngine.popen_uci(args.stockfish) as sf:
        options = {name: value for name, value in {'Threads': 1, 'Hash': 64, 'Skill Level': 20}.items()
                   if name in sf.options}
        sf.configure(options)
        version = str(sf.id.get('name', 'Unknown'))
        if not version.startswith('Stockfish 19'):
            raise AssertionError(f'Expected official Stockfish 19, got {version}')
        for game_id, game in archived:
            board = game.board()
            gm_color = chess.WHITE if game.headers['White'] == 'GM-1000' else chess.BLACK
            moves = []
            for ply, move in enumerate(game.mainline_moves(), start=1):
                turn = board.turn
                who = 'gm' if turn == gm_color else 'opponent'
                key = book_key(board)
                gm_entry = gm_positions.get(key, {})
                sf_entry = sf_positions.get(key, {})
                gm_top = next(iter(sorted(gm_entry.items(), key=lambda kv: (-kv[1]['count'], kv[0]))), None)
                sf_preferred = sf_entry.get('preferred_move')
                san = board.san(move)
                best_cp, best = analysis_score(sf, board, args.analysis_seconds)
                played_cp, _ = analysis_score(sf, board, args.analysis_seconds, only_move=move)
                loss = max(0, best_cp - played_cp) if best_cp is not None and played_cp is not None else None
                item = {
                    'ply': ply, 'move_number': board.fullmove_number, 'phase': phase(ply),
                    'side': who, 'san': san, 'uci': move.uci(),
                    'best_uci': best.uci() if best else None,
                    'best_san': board.san(best) if best else None,
                    'cp_loss': loss, 'best_cp': best_cp, 'played_cp': played_cp,
                    'in_gm_memory': bool(gm_entry), 'in_sf_memory': bool(sf_entry),
                    'gm_top_uci': gm_top[0] if gm_top else None,
                    'sf_preferred_uci': sf_preferred,
                    'followed_gm_top': bool(gm_top and move.uci() == gm_top[0]),
                    'followed_sf_preferred': bool(sf_preferred and move.uci() == sf_preferred),
                    'fen': board.fen() if loss is not None and loss >= 100 else None,
                }
                moves.append(item)
                board.push(move)
            outcome = game.headers['Result']
            if outcome == '1/2-1/2':
                result = 'draw'
            elif outcome == '*':
                result = 'incomplete'
            else:
                won = (outcome == '1-0') == (gm_color == chess.WHITE)
                result = 'win' if won else 'loss'
            gm_bad = [x for x in moves if x['side'] == 'gm' and x['cp_loss'] is not None and x['cp_loss'] >= 200]
            opp_bad = [x for x in moves if x['side'] == 'opponent' and x['cp_loss'] is not None and x['cp_loss'] >= 200]
            largest = sorted((x for x in moves if x['side'] == 'gm' and x['cp_loss'] is not None), key=lambda x: -x['cp_loss'])[:5]
            game_record = {
                'id': game_id, 'result': result,
                'gm_color': 'white' if gm_color else 'black',
                'plies': board.ply(), 'termination': game.headers.get('Termination'),
                'first_gm_mistake_200cp': gm_bad[0] if gm_bad else None,
                'first_opponent_mistake_200cp': opp_bad[0] if opp_bad else None,
                'five_largest_gm_errors': largest,
                'moves': moves,
            }
            cases.append(game_record)
            print(f"ANALYZED {game_id} {result} GM={game_record['gm_color']} plies={board.ply()} "
                  f"GM>=200cp={len(gm_bad)} Opp>=200cp={len(opp_bad)}",flush=True)
            (args.output_dir/'progress.json').write_text(json.dumps({'games_analyzed':len(cases), 'games':[{k:v for k,v in case.items() if k!='moves'} for case in cases]},indent=2)+'\n',encoding='utf-8')

    outcomes = Counter(g['result'] for g in cases)
    if outcomes != {'loss': 12, 'win': 2, 'draw': 2}:
        raise AssertionError(f'Unexpected outcomes: {outcomes}')
    groups = {outcome: describe_group([g for g in cases if g['result'] == outcome])
              for outcome in ('win', 'draw', 'loss')}
    colors = {color: describe_group(cases,color=color) for color in ('white','black')}
    all_errors = sorted(({'game':g['id'], 'result':g['result'], 'gm_color':g['gm_color'],
                          **m} for g in cases for m in g['moves']
                         if m['side']=='gm' and m['cp_loss'] is not None),key=lambda row:-row['cp_loss'])
    timeline = []
    for g in cases:
        b=g['first_gm_mistake_200cp']
        timeline.append({'game':g['id'],'result':g['result'],'gm_color':g['gm_color'],'first_gm_200cp':
                         {k:b[k] for k in ('ply','san','uci','best_san','cp_loss','phase','fen')} if b else None,
                         'gm_200cp_count':sum(m['side']=='gm' and m['cp_loss'] is not None and m['cp_loss']>=200 for m in g['moves']),
                         'gm_moves':sum(m['side']=='gm' for m in g['moves'])})
    summary = {
        'schema': 1, 'created_utc':datetime.now(timezone.utc).isoformat(),
        'source_run_id':41195883523,
        'source_artifact':'gm1000-stockfish-skill5-four-tournaments',
        'original_pgn_sha256':sources_sha,
        'stockfish_analyst':version, 'analyst_skill_level':20,
        'analysis_seconds_per_root':args.analysis_seconds,
        'analyst_method':'best-move root search vs forced-played-move root search; same time per root; cp_loss=max(0,best_cp-played_cp)',
        'opponent_in_original_games':'Stockfish Ubuntu package Skill Level 5; 0.2s per move',
        'games':len(cases), 'outcomes':dict(outcomes),
        'by_result':groups, 'by_color':colors,
        'earliest_major_errors_by_game':timeline,
        'top_30_gm_errors':all_errors[:30],
        'limitations':[
            'Short independent analysis time; evaluation and cp loss can fluctuate at larger search depths.',
            'One forced-root evaluation and one independent best-root evaluation per move; they can differ in depth and evaluation volatility.',
            'Mate scores use 10000cp cap, so checkmate mistakes can dominate average cp loss; use medians and counts also.',
            'Game outcome does not establish which earlier move caused the result.',
            'Only two wins and two draws; no claim about Elo or statistically reliable strength differences.',
            'No engine-model or grandmaster/Stockfish memory changed by this experiment.'
        ]
    }
    detail={'schema':1,'source_run_id':41195883523,'games':cases}
    (args.output_dir/'forensic_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (args.output_dir/'all_moves.json').write_text(json.dumps(detail,indent=2)+'\n',encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pgn-dir',type=Path,default=ROOT/'reports'/'original-skill5')
    p.add_argument('--output-dir',type=Path,default=ROOT/'reports'/'skill5-forensic')
    p.add_argument('--stockfish',default=os.environ.get('STOCKFISH_PATH','/usr/games/stockfish'))
    p.add_argument('--analysis-seconds',type=float,default=.08)
    args=p.parse_args()
    run(args)


if __name__=='__main__':
    main()