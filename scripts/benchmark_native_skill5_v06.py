"""Fixed-opening A/B versus Stockfish Skill 5, with memory and book disabled.

16 games per candidate (eight FENs, both colors), same 0.2s move budget,
stockfish Skill Level 5, identical machine class. Explicitly low sample size;
we cannot assign an Elo or promote automatically based on this experiment.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import json,os,sys,shutil
from pathlib import Path
import chess,chess.engine,chess.pgn
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.stockfish19_selfplay400 import varied_opening_positions

def run(args):
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    sf=args.stockfish or os.environ.get('STOCKFISH_PATH') or shutil.which('stockfish') or '/usr/games/stockfish'
    assert Path(sf).is_file(), 'Stockfish executable not found'
    assert args.native.is_file(), 'GM-1000 native executable not found'
    book=json.loads((ROOT/'data/opening_book.json').read_text(encoding='utf-8'))
    seeds=varied_opening_positions(book,pairs=args.pairs,seed=args.seed)
    results={};all_games=[]
    for variant in (('native',) if args.native_only else ('python','native')):
        cmd=([sys.executable,'-u','-m','engine.uci'] if variant=='python' else str(args.native))
        record=Counter();games=[]
        with chess.engine.SimpleEngine.popen_uci(cmd,cwd=str(ROOT),timeout=15) as gm, \
             chess.engine.SimpleEngine.popen_uci(sf,timeout=15) as opponent:
            opponent.configure({'Skill Level':5,'Threads':1,'Hash':16})
            if variant=='python':
                gm.configure({'PositionMemory':False,'StockfishMemory':False,'OwnBook':False,
                              'Learning':False,'LearnedEval':False})
            with (out/f'{variant}-matches.pgn').open('w',encoding='utf-8') as stream:
                for idx in range(args.pairs*2):
                    gm_color=chess.WHITE if idx%2==0 else chess.BLACK
                    seed=seeds[idx//2]
                    board=chess.Board(seed['fen'])
                    game=chess.pgn.Game();game.setup(board)
                    game.headers.update({'Event':'GM-1000 v0.6 independent Skill5 A/B',
                      'Round':str(idx+1),'White':variant if gm_color else 'Stockfish5',
                      'Black':'Stockfish5' if gm_color else variant,
                      'TimeSeconds':str(args.seconds),'SkillLevel':'5',
                      'Memory':'both off','EngineVariant':variant})
                    node=game;token=object();error=None
                    for ply in range(args.max_plies):
                        if board.is_game_over(claim_draw=True):break
                        engine=gm if board.turn==gm_color else opponent
                        try:
                            reply=engine.play(board,chess.engine.Limit(time=args.seconds),game=token)
                            if reply.move not in board.legal_moves:
                                raise RuntimeError('illegal or null returned move')
                            node=node.add_variation(reply.move);board.push(reply.move)
                        except Exception as exc:
                            error=f'{type(exc).__name__}: {exc}'
                            break
                    outcome=board.outcome(claim_draw=True)
                    if error:
                        record['errors']+=1;result='*';term='engine_error'
                    elif outcome:
                        record['completed']+=1;result=outcome.result();term=outcome.termination.name
                        if outcome.winner is None: record['draws']+=1
                        elif outcome.winner==gm_color:record['wins']+=1
                        else:record['losses']+=1
                    else:
                        record['incomplete']+=1;result='*';term='move_cap'
                    game.headers['Result']=result;game.headers['Termination']=term
                    stream.write(str(game)+'\n\n');stream.flush()
                    row={'variant':variant,'game':idx+1,'paired_opening':idx//2+1,
                         'gm_color':'white' if gm_color else 'black','result':result,
                         'plies':board.ply(),'termination':term,'error':error}
                    games.append(row);all_games.append(row)
                    print('SKILL5_MATCH',variant,idx+1,dict(record),flush=True)
                    (out/'progress.json').write_text(json.dumps({'counts':dict(record),'games':all_games},indent=2)+'\n')
        completed=record['completed']
        results[variant]={'wins':record['wins'],'draws':record['draws'],'losses':record['losses'],
                          'completed':completed,'errors':record['errors'],'incomplete':record['incomplete'],
                          'score_percent':round(100*(record['wins']+.5*record['draws'])/completed,2) if completed else None,
                          'games':games}
    report={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
            'study':('native GM-1000 independent extended Stockfish Skill 5 tournament' if args.native_only else 'native vs Python GM-1000 independent Stockfish Skill 5 A/B'),
            'opening_seed':args.seed,'native_only':args.native_only,'pairs':args.pairs,
            'seconds_per_move':args.seconds,'skill_level':5,'paired_opening_fens':[x['fen'] for x in seeds],
            'variants':results,'limitations':'16 games per version, stochastic opponent, 0.2s/move. Native has different simplified handcrafted evaluator; neither has memories. Not an Elo estimate. No promotion without larger replica.'}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('SKILL5_A_B_FINAL',json.dumps({k:v for k,v in report.items() if k!='paired_opening_fens' and k!='variants'}|{'scores':{name:{k:v for k,v in x.items() if k!='games'} for name,x in results.items()}},indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,default=ROOT/'native/bin/gm1000-native')
    parser.add_argument('--stockfish',default=None)
    parser.add_argument('--seconds',type=float,default=.2)
    parser.add_argument('--pairs',type=int,default=8)
    parser.add_argument('--seed',type=int,default=260637)
    parser.add_argument('--native-only',action='store_true')
    parser.add_argument('--max-plies',type=int,default=220)
    parser.add_argument('--out',type=Path,default=ROOT/'reports/native-v06-skill5')
    args=parser.parse_args()
    assert .02<=args.seconds<=1 and 1<=args.pairs<=40 and args.max_plies>=20
    run(args)