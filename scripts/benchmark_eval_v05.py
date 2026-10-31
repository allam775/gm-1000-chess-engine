"""Paired-opening Stockfish-5 validation of learned evaluation vs handcrafted.

Exactly the same opening seeds, colors, time control, search, and NO memory are
used for both variants. Only the evaluator switch changes. No trained model is
promoted on the basis of a small tournament.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import chess
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from engine.learned_eval import LinearEvaluator
from scripts.stockfish19_selfplay400 import varied_opening_positions
from scripts.arena import run as arena_run


def aggregate(result):
    games=result['completed_games']
    return {k:result[k] for k in ('wins','draws','losses','completed_games','errors','incomplete','score_percent')}


def run(args):
    if args.games != 16 or args.skill != 5:
        raise ValueError('Validation requires exactly 16 games per variant vs Skill5')
    if not args.candidate.is_file():raise FileNotFoundError('Missing candidate position-evaluation model')
    model=LinearEvaluator.load(args.candidate)
    model_sha=hashlib.sha256(args.candidate.read_bytes()).hexdigest()
    book=json.loads((ROOT/'data/opening_book.json').read_text(encoding='utf-8'))
    opening_seeds=varied_opening_positions(book,pairs=args.games//2,seed=53819)
    fens=[pos['fen'] for pos in opening_seeds for _ in (0,1)]
    assert len(fens)==args.games
    stockfish_bin=args.stockfish or os.environ.get('STOCKFISH_PATH') or shutil.which('stockfish')
    if not stockfish_bin and Path('/usr/games/stockfish').exists():
        stockfish_bin='/usr/games/stockfish'
    if not stockfish_bin:raise FileNotFoundError('Stockfish opponent unavailable')
    args.output.mkdir(parents=True,exist_ok=True)
    data=[]
    for mode in (False,True):
        cfg=SimpleNamespace(games=args.games,stockfish_skill=5,
                            seconds_per_move=args.seconds_per_move,
                            max_plies=args.max_plies,stockfish=stockfish_bin,
                            output_dir=args.output/('candidate' if mode else 'baseline'),
                            own_book=False,learning=False,
                            position_memory=False,stockfish_memory=False,
                            learned_eval=mode,starting_fens=fens)
        result=arena_run(cfg)
        if result['config']['learned_eval']!=mode or result['config']['position_memory']:
            raise AssertionError('Treatment variant configuration incorrect')
        data.append(result)
        print('EVALUATOR_VARIANT_RESULT', 'learned' if mode else 'handcrafted',
              json.dumps(aggregate(result),sort_keys=True),flush=True)
    a,b=map(aggregate,data)
    if sum(x['completed_games']+x['errors']+x['incomplete'] for x in (a,b)) != 32:
        raise AssertionError('Missing games')
    report={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
            'objective':'A/B static evaluator only (memory OFF both, own book OFF both)',
            'model_file_sha256':model_sha,
            'model_version':model.version,
            'opponent':'Stockfish Ubuntu Skill Level 5','skill_level':5,
            'seconds_per_move':args.seconds_per_move,
            'game_count_per_variant':args.games,
            'total_games':args.games*2,
            'opening_seed':53819,'opening_fens':fens,
            'handcrafted':a,'learned':b,
            'difference_score_pct':round((b['score_percent'] or 0)-(a['score_percent'] or 0),2),
            'stronger_on_this_sample':b['score_percent']>a['score_percent'] if b['score_percent'] is not None and a['score_percent'] is not None else None,
            'promoted':False,
            'limitations':'16 games per version against one stochastic opponent; not a rating. Source openings may overlap by transposition with teacher games. No promotion without replicated larger independent validation.'}
    (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('FINAL_V05_BENCHMARK',json.dumps({k:v for k,v in report.items() if k!='opening_fens'},indent=2),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stockfish',default=None)
    p.add_argument('--games',type=int,default=16)
    p.add_argument('--skill',type=int,default=5)
    p.add_argument('--seconds-per-move',type=float,default=0.2)
    p.add_argument('--max-plies',type=int,default=280)
    p.add_argument('--candidate',type=Path,default=ROOT/'data/learned_eval_v05_candidate.json')
    p.add_argument('--output',type=Path,default=ROOT/'reports/v05-evaluator-benchmark')
    run(p.parse_args())