"""Head-to-head native GM-1000 vs Python v0.5 on paired opening seeds.

An isolated search contest: both historical memories, book, and v0.5 learned
weights OFF for Python. Native uses its own simple handcrafted evaluator and
fast C++ alpha-beta; do not attribute all improvement exclusively to speed.
Results preserve every original PGN and count unfinished games separately.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time

import chess
import chess.engine
import chess.pgn
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.stockfish19_selfplay400 import varied_opening_positions
from scripts.profile_search_v06 import sample_positions,fresh_engine


def time_depth_comparison(native:Path,seconds:float,limit:int):
    rows=[]
    for p in sample_positions(max_positions=limit):
        b=chess.Board(p['fen'])
        py=fresh_engine()
        before=time.perf_counter()
        pr=py.search(b,time_limit=seconds,depth=14,allow_book=False)
        t=time.perf_counter()-before
        nr=json.loads(__import__('subprocess').check_output([str(native),'--bench',b.fen(),str(round(seconds*1000))],text=True,timeout=8))
        nm=chess.Move.from_uci(nr['bestmove'])
        assert pr.move in b.legal_moves and nm in b.legal_moves
        rows.append({'id':p['id'],'python_depth':pr.depth,'python_nodes':pr.nodes,'python_nps':round(pr.nodes/max(t,1e-9)),
                     'native_depth':nr['depth'],'native_nodes':nr['nodes'],'native_nps':nr['nps']})
    return {'positions':len(rows),'median_python_depth':statistics.median(x['python_depth'] for x in rows),
            'median_native_depth':statistics.median(x['native_depth'] for x in rows),
            'median_python_nps':statistics.median(x['python_nps'] for x in rows),
            'median_native_nps':statistics.median(x['native_nps'] for x in rows), 'positions_detail':rows}


def play_paired(native:Path,seconds:float,pairs:int,output:Path,opponent:str='python',max_plies:int=220):
    book=json.loads((ROOT/'data/opening_book.json').read_text(encoding='utf-8'))
    seeds=varied_opening_positions(book,pairs=pairs,seed=260631)
    cfg={'OwnBook':False,'PositionMemory':False,'StockfishMemory':False,'Learning':False,'LearnedEval':False}
    counts=Counter();games=[]
    with chess.engine.SimpleEngine.popen_uci(str(native),timeout=15) as native_engine, \
         chess.engine.SimpleEngine.popen_uci([sys.executable,'-u','-m','engine.uci'],cwd=str(ROOT),timeout=15) as python_engine:
        python_engine.configure(cfg)
        with (output/'matches.pgn').open('w',encoding='utf-8') as f:
            for ix in range(pairs*2):
                seed=seeds[ix//2]
                board=chess.Board(seed['fen'])
                native_color=chess.WHITE if ix%2==0 else chess.BLACK
                game=chess.pgn.Game();game.setup(board)
                game.headers.update({'Event':'GM-1000 native-vs-Python paired validation',
                  'Round':str(ix+1),'White':'NativeGM1000' if native_color==chess.WHITE else 'PythonGM1000',
                  'Black':'PythonGM1000' if native_color==chess.WHITE else 'NativeGM1000',
                  'TimeSeconds':str(seconds),'Source':'paired book FEN, memory and learned eval off'})
                token=object();node=game;error=None
                for p in range(max_plies):
                    if board.is_game_over(claim_draw=True):break
                    eng=native_engine if board.turn==native_color else python_engine
                    try:
                        reply=eng.play(board,chess.engine.Limit(time=seconds),game=token)
                        if reply.move not in board.legal_moves:raise RuntimeError('illegal or null returned move')
                        node=node.add_variation(reply.move);board.push(reply.move)
                    except Exception as ex:
                        error=f'{type(ex).__name__}: {ex}'
                        break
                outcome=board.outcome(claim_draw=True)
                if error:
                    counts['errors']+=1;result='*';term='error'
                elif outcome:
                    counts['completed']+=1;result=outcome.result();term=outcome.termination.name
                    if outcome.winner is None:counts['draws']+=1
                    elif outcome.winner==native_color:counts['native_wins']+=1
                    else:counts['python_wins']+=1
                else:
                    counts['incomplete']+=1;result='*';term='move_cap'
                game.headers['Result']=result
                game.headers['Termination']=term
                f.write(str(game)+'\n\n');f.flush()
                games.append({'index':ix+1,'opening_pair':ix//2+1,'color':'white' if native_color else 'black',
                              'result':result,'termination':term,'plies':board.ply(),'error':error})
                print('GAME_DONE',ix+1,dict(counts),flush=True)
                (output/'progress.json').write_text(json.dumps({'counts':dict(counts),'games':games},indent=2)+'\n')
    complete=counts['completed']
    return {'total_games':pairs*2,'played':len(games),'completed':complete,'native_wins':counts['native_wins'],
        'python_wins':counts['python_wins'],'draws':counts['draws'],'errors':counts['errors'],
        'incomplete':counts['incomplete'],
        'native_score_percent':round(100*(counts['native_wins']+.5*counts['draws'])/complete,2) if complete else None,
        'games':games,'opening_fens':[s['fen'] for s in seeds]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native',type=Path,default=ROOT/'native/bin/gm1000-native')
    p.add_argument('--seconds',type=float,default=0.2)
    p.add_argument('--pairs',type=int,default=12)
    p.add_argument('--profile-positions',type=int,default=16)
    p.add_argument('--out',type=Path,default=ROOT/'reports/native-v06')
    a=p.parse_args();assert .02<=a.seconds<=1 and 1<=a.pairs<=40
    a.out.mkdir(parents=True,exist_ok=True)
    profile=time_depth_comparison(a.native,a.seconds,a.profile_positions)
    (a.out/'speed.json').write_text(json.dumps(profile,indent=2)+'\n')
    print('SPEED',json.dumps({k:v for k,v in profile.items() if k!='positions_detail'}),flush=True)
    match=play_paired(a.native,a.seconds,a.pairs,a.out)
    summary={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
             'experiment':'GM-1000 native C++ v0.6 compared with Python v0.5 no memories/book',
             'seconds_per_move':a.seconds,'speed':{k:v for k,v in profile.items() if k!='positions_detail'},
             'match':match,'native_version':'v0.6-experimental',
             'limitations':'Evaluation differences confound search-only causal comparison. 24 games are a small skill sample, not Elo. Match from paired historical book FENs.'}
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('NATIVE_V06_SUMMARY',json.dumps({**summary,'match':{k:v for k,v in match.items() if k not in ('games','opening_fens')}},indent=2),flush=True)

if __name__=='__main__':main()