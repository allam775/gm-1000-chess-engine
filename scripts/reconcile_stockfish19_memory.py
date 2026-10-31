"""Score Stockfish19 self-play positions, reconcile competing choices conservatively.

Game outcome is assigned from THE MOVING SIDE'S perspective. Historical GM
moves have no attached outcomes and must not be treated as losses. Conflicting
moves are additionally compared by independent Stockfish 19 analysis of the
same exact position; an uncertain comparison keeps the old GM preference.
All candidates remain in the record even when not preferred.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engine.search import book_key


def player_points(result: str, color: bool) -> str | None:
    if result == '1/2-1/2':
        return 'draws'
    if result == '1-0':
        return 'wins' if color == chess.WHITE else 'losses'
    if result == '0-1':
        return 'wins' if color == chess.BLACK else 'losses'
    return None


def record_games(pgn_path: Path) -> tuple[dict, dict]:
    positions = defaultdict(lambda: defaultdict(Counter))
    games, completed, errors, incomplete = 0, 0, 0, 0
    with pgn_path.open(encoding='utf-8') as f:
        while (game := chess.pgn.read_game(f)) is not None:
            if game.errors:
                raise ValueError('Invalid saved PGN')
            games += 1
            result = game.headers.get('Result','*')
            if result not in ('1-0','0-1','1/2-1/2','*'):
                raise ValueError('Unexpected result')
            if result == '*':
                if game.headers.get('Termination')=='engine_error':
                    errors += 1
                else:
                    incomplete += 1
            else:
                completed += 1
            board = game.board()
            for move in game.mainline_moves():
                key = book_key(board)
                values = positions[key][move.uci()]
                values['observations'] += 1
                label = player_points(result, board.turn)
                if label:
                    values[label] += 1
                board.push(move)
    return positions, {'games':games,'completed':completed,'errors':errors,'incomplete':incomplete}


def side_score(row: dict):
    n = row.get('wins',0)+row.get('draws',0)+row.get('losses',0)
    return (row.get('wins',0)+0.5*row.get('draws',0))/n if n else None


def evaluate_alternatives(engine, board, choices: list[str], *, seconds: float) -> dict[str,int]:
    """Comparable same-position multipv root analysis, CP from player to move."""
    candidates = []
    for uci in choices:
        try:
            m = chess.Move.from_uci(uci)
            if m in board.legal_moves:
                candidates.append(m)
        except ValueError:
            continue
    if not candidates:
        return {}
    try:
        data = engine.analyse(board, chess.engine.Limit(time=seconds),
                              root_moves=candidates, multipv=len(candidates))
        if isinstance(data, dict):
            data=[data]
        scores = {}
        for pv_info in data:
            line = pv_info.get('pv',[])
            if line and line[0] in candidates and pv_info.get('score') is not None:
                cp = pv_info['score'].pov(board.turn).score(mate_score=100000)
                if cp is not None:
                    scores[line[0].uci()]=int(cp)
        return scores
    except (chess.engine.EngineError, chess.engine.EngineTerminatedError, ValueError):
        return {}


def choose_preferred(sf: dict, old: dict, evaluations: dict, *, min_gain_cp: int = 20) -> tuple[str,str]:
    """Keep legacy GM choice unless a new evaluated option is clearly better.

    For competing Stockfish moves, prefer outcome for sufficiently repeated,
    near-equal-score continuations. Otherwise prefer higher analysis score.
    """
    old_best = max(old, key=lambda move:(old[move].get('count',0), move)) if old else None
    if old_best and (len(sf)==1 and old_best in sf):
        return old_best, 'agreement'
    sf_moves = sorted(sf)
    if not sf_moves:
        return old_best, 'historical_only'
    valid_scores = {m:evaluations[m] for m in sf_moves if m in evaluations}
    if valid_scores:
        top = max(valid_scores.values())
        comparable = [m for m in sf_moves if m in valid_scores and valid_scores[m] >= top-15]
        # Outcomes count only if >=2 *completed* game observations, otherwise unreliable.
        def sf_order(m):
            count=sf[m].get('wins',0)+sf[m].get('draws',0)+sf[m].get('losses',0)
            return (1 if count>=2 else 0,
                    side_score(sf[m]) if count>=2 else .5,
                    valid_scores[m],sf[m]['observations'],m)
        sf_best=max(comparable,key=sf_order)
    else:
        sf_best = max(sf_moves, key=lambda m:(
            side_score(sf[m]) if side_score(sf[m]) is not None else .5,
            sf[m]['observations'],m))
    if not old_best:
        return sf_best, 'stockfish_outcome_and_analysis' if valid_scores else 'stockfish_observed'
    if sf_best==old_best:
        return sf_best, 'agreement'
    # Compare same board by the strongest analyzed old move, not wins from a
    # different human game or a heuristic assumption that SF must always win.
    gm_scores = {m:evaluations[m] for m in old if m in evaluations}
    if sf_best not in evaluations or not gm_scores:
        return old_best, 'historical_retained_unverified'
    best_gm=max(gm_scores.values())
    if evaluations[sf_best] >= best_gm + min_gain_cp:
        return sf_best, 'stockfish_evaluated_gain'
    return max(gm_scores, key=lambda m:(gm_scores[m],old[m].get('count',0),m)), 'historical_retained_close_or_better'


def run(args):
    root = ROOT/'reports/stockfish19-skill20-400'
    original = json.loads((ROOT/'data/position_memory.json').read_text(encoding='utf-8'))
    games_report = json.loads((root/'games_report.json').read_text(encoding='utf-8'))
    if original.get('source_games') != 560 or games_report.get('games_recorded')!=400 or games_report.get('skill_level')!=20:
        raise ValueError('Incorrect source game or Stockfish study snapshot')
    seen, counts = record_games(root/'matches.pgn')
    if counts['games'] != 400 or counts['errors']:
        raise ValueError('Cannot reconcile without 400 saved error-free games')
    stockfish_path = Path(args.stockfish or os.environ.get('STOCKFISH_PATH',''))
    if not stockfish_path.is_file():
        raise FileNotFoundError('Pinned official Stockfish 19 required for conflict analysis')
    old_positions=original['positions']
    overlay={}
    conflicts, changed, preserved, agreements, new_positions, evaluated, unresolved=0,0,0,0,0,0,0
    with chess.engine.SimpleEngine.popen_uci(str(stockfish_path)) as engine:
        if 'Stockfish 19' not in engine.id.get('name',''):
            raise ValueError('Wrong analysis engine')
        engine.configure({'Threads':1,'Hash':32,'Skill Level':20})
        for index,(epd,moves) in enumerate(sorted(seen.items()),1):
            old=old_positions.get(epd,{})
            stockfish={uci:dict(counter) for uci,counter in moves.items()}
            choices=set(stockfish)|set(old)
            conflicting=len(choices)>1
            scores={}
            if conflicting:
                conflicts+=1
                b=chess.Board(epd+' 0 1')
                # Evaluate at most 12 candidates; additional moves stay in the audit.
                candidates=sorted(choices,key=lambda m:(
                    stockfish.get(m,{}).get('observations',0)+old.get(m,{}).get('count',0)),reverse=True)[:12]
                scores=evaluate_alternatives(engine,b,candidates,seconds=args.eval_time)
                if len(scores)>1:
                    evaluated+=1
                else:
                    unresolved+=1
            preferred,reason=choose_preferred(stockfish,old,scores)
            if old:
                old_best=max(old,key=lambda m:(old[m].get('count',0),m))
                if preferred!=old_best:
                    changed+=1
                elif reason=='agreement':
                    agreements+=1
                else:
                    preserved+=1
            else:
                new_positions+=1
            overlay[epd]={
                'preferred_move':preferred,
                'selection_reason':reason,
                'candidates':{
                    m:{'stockfish':stockfish.get(m,{}),
                       'grandmasters':old.get(m,{}),
                       **({'eval_cp':scores[m]} if m in scores else {})}
                    for m in sorted(choices)
                }
            }
            if index%3000==0:
                print('RECONCILE',index,'positions',conflicts,'conflicts',changed,'changed',flush=True)
    snapshot={
        'schema':1,'source':'Stockfish 19 Skill Level 20 freshly generated 400-game self-play, preserved GM base',
        'engine_version':games_report['stockfish'],'stockfish_skill':20,
        'games':400,'completed_games':counts['completed'],'incomplete_games':counts['incomplete'],
        'historical_gm_source_games':560,'historical_gm_positions':original['positions_count'],
        'positions_count':len(overlay),'conflicting_positions':conflicts,
        'gm_preferences_changed':changed,'gm_preferences_preserved':preserved,
        'gm_preferences_agreed':agreements,'new_positions':new_positions,
        'analyzed_conflicts':evaluated,'unresolved_conflicts':unresolved,
        'eval_seconds_per_conflict':args.eval_time,
        'selection':'Outcome from side to move; Stockfish19 same-position root analysis; ≥20cp to supersede remembered GM move; retain old GM when uncertain',
        'limitations':'Self-play result is not objective move quality. Incomplete games have no outcome. Search scores are finite-time approximations. No claim of Elo gain.',
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'positions':overlay}
    dest=ROOT/'data/stockfish19_position_memory.json'
    dest.write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    summary={k:v for k,v in snapshot.items() if k!='positions'}
    summary['stockfish_position_observations']=sum(x['observations'] for row in seen.values() for x in row.values())
    summary['original_gm_memory_unchanged']=True
    (ROOT/'data/stockfish19_position_memory_report.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    (root/'reconciliation_report.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print('RECONCILIATION_REPORT',json.dumps(summary,indent=2),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stockfish',default=None)
    p.add_argument('--eval-time',type=float,default=.04)
    run(p.parse_args())


if __name__=='__main__':
    main()
