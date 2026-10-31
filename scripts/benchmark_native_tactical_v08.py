"""Fixed-source paired native v0.8 vs native v0.7, blind to opponent results.

Uses independent opening seed, 0.2s per move, alternating colors, own engines
with no memory/book/Stockfish search. Preserve PGN and game-by-game evidence.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,sys
from pathlib import Path
import chess,chess.engine,chess.pgn
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.stockfish19_selfplay400 import varied_opening_positions

BASE_SHA='26cdee9b59641a24be88a8574418d9d12e25c3e0'
def run(args):
    assert args.candidate.is_file() and args.baseline.is_file()
    book=json.loads((ROOT/'data/opening_book.json').read_text(encoding='utf-8'))
    seeds=varied_opening_positions(book,pairs=args.pairs,seed=args.seed)
    args.out.mkdir(parents=True,exist_ok=True)
    records=[];counts=Counter()
    pgn=args.out/'candidate-v08-vs-frozen-v07.pgn'
    with chess.engine.SimpleEngine.popen_uci(str(args.candidate.resolve()),timeout=15) as cand, \
        chess.engine.SimpleEngine.popen_uci(str(args.baseline.resolve()),timeout=15) as base, \
        pgn.open('w',encoding='utf-8') as stream:
        for n in range(args.pairs*2):
            c=chess.WHITE if n%2==0 else chess.BLACK
            board=chess.Board(seeds[n//2]['fen'])
            game=chess.pgn.Game();game.setup(board)
            game.headers.update({'Event':'GM1000 v08 vs v07 tactical search independent validation',
                'Round':str(n+1),'White':'v08' if c else 'v07',
                'Black':'v07' if c else 'v08','TimeSeconds':str(args.seconds),
                'OpeningSeed':str(args.seed),'FrozenBaselineSHA':BASE_SHA})
            node=game;game_token=object();error=None
            for ply in range(args.max_plies):
                if board.is_game_over(claim_draw=True):break
                e=cand if board.turn==c else base
                try:
                    reply=e.play(board,chess.engine.Limit(time=args.seconds),game=game_token)
                    if reply.move is None or reply.move not in board.legal_moves:
                        raise RuntimeError('illegal or null move')
                    node=node.add_variation(reply.move);board.push(reply.move)
                except Exception as exc:
                    error=f'{type(exc).__name__}: {exc}';break
            outcome=board.outcome(claim_draw=True)
            if error: status='error';result='*'
            elif not outcome: status='incomplete';result='*'
            else:
                result=outcome.result()
                status=('draw' if outcome.winner is None else 'win' if outcome.winner==c else 'loss')
            counts[status]+=1
            game.headers['Result']=result
            game.headers['Termination']=outcome.termination.name if outcome else status
            stream.write(str(game)+'\n\n');stream.flush()
            records.append({'game':n+1,'opening':n//2,'color':'white' if c else 'black',
               'outcome':status,'result':result,'plies_after_seed':len(list(game.mainline_moves())),
               'error':error})
            (args.out/'progress.json').write_text(json.dumps({'games':records,'counts':dict(counts)},indent=2)+'\n')
            print('V08_DIRECT',n+1,dict(counts),flush=True)
    completed=counts['win']+counts['draw']+counts['loss']
    by={color:Counter(g['outcome'] for g in records if g['color']==color) for color in ('white','black')}
    report={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
         'experiment':'v08 vs frozen v07 direct, paired openings',
         'frozen_baseline_sha':BASE_SHA,'opening_seed':args.seed,
         'fens':[x['fen'] for x in seeds], 'games':records,'pairs':args.pairs,
         'seconds_per_move':args.seconds,
         'counts':dict(counts), 'completed':completed,
         'score_percent':round(100*(counts['win']+.5*counts['draw'])/completed,2) if completed else None,
         'by_color':{k:dict(v) for k,v in by.items()},
         'pgn_sha256':hashlib.sha256(pgn.read_bytes()).hexdigest(),
         'limitations':'Small exploratory sample, independent seed, no Elo. Do not promote without external control.'}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('V08_DIRECT_FINAL',json.dumps({k:v for k,v in report.items() if k not in ('fens','games')},indent=2),flush=True)
    if counts['error'] or counts['incomplete'] or completed!=2*args.pairs:
        raise RuntimeError('Missing/invalid games, cannot claim win rate')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,default=ROOT/'build/tournament/v08')
    p.add_argument('--baseline',type=Path,default=ROOT/'build/tournament/v07')
    p.add_argument('--out',type=Path,default=ROOT/'reports/native-v08-direct')
    p.add_argument('--pairs',type=int,default=16)
    p.add_argument('--seed',type=int,default=26103208)
    p.add_argument('--seconds',type=float,default=.2)
    p.add_argument('--max-plies',type=int,default=220)
    a=p.parse_args()
    assert 1<=a.pairs<=50 and .04<=a.seconds<=2 and 120<=a.max_plies<=400
    run(a)