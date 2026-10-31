"""Paired-opening native tactical-v0.7 vs untouched native-v0.6 head-to-head.

Compiles distinct C++ engines in CI; no historical memory, no Stockfish
engine to play moves, alternating colors for every opening. No autopromotion.
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


def run(args):
    if not 1<=args.pairs<=80 or not .04<=args.seconds<=2 or not 80<=args.max_plies<=400:
        raise ValueError('Unsupported match configuration')
    assert args.candidate.is_file() and args.baseline.is_file()
    book=json.loads((ROOT/'data/opening_book.json').read_text(encoding='utf-8'))
    seeds=varied_opening_positions(book,pairs=args.pairs,seed=args.seed)
    args.out.mkdir(parents=True,exist_ok=True)
    records=[]; counts=Counter()
    with chess.engine.SimpleEngine.popen_uci(str(args.candidate.resolve()),timeout=15) as candidate, \
         chess.engine.SimpleEngine.popen_uci(str(args.baseline.resolve()),timeout=15) as baseline, \
         (args.out/'tactical-v07-vs-native-v06.pgn').open('w',encoding='utf-8') as stream:
        for n in range(2*args.pairs):
            cand_color=chess.WHITE if n%2==0 else chess.BLACK
            opening=seeds[n//2]
            board=chess.Board(opening['fen'])
            game=chess.pgn.Game();game.setup(board)
            game.headers.update({'Event':'GM1000 independent tactical v07 vs native v06',
                'Round':str(n+1),'White':'Candidate-v07' if cand_color else 'Baseline-v06',
                'Black':'Baseline-v06' if cand_color else 'Candidate-v07',
                'TimeSeconds':str(args.seconds),'OpeningSeed':str(args.seed),
                'CandidateBaseSHA':args.base_sha,'EngineVariant':'native paired A/B'})
            node=game;token=object();error=None
            for ply in range(args.max_plies):
                if board.is_game_over(claim_draw=True):break
                player=candidate if board.turn==cand_color else baseline
                try:
                    response=player.play(board,chess.engine.Limit(time=args.seconds),game=token)
                    if response.move is None or response.move not in board.legal_moves:
                        raise RuntimeError('missing or illegal UCI move')
                    node=node.add_variation(response.move)
                    board.push(response.move)
                except Exception as exc:
                    error=f'{type(exc).__name__}: {exc}';break
            outcome=board.outcome(claim_draw=True)
            if error:
                status='error';counts['errors']+=1;result='*'
            elif outcome:
                result=outcome.result()
                if outcome.winner is None:status='draw';counts['draws']+=1
                elif outcome.winner==cand_color:status='win';counts['wins']+=1
                else:status='loss';counts['losses']+=1
                counts['completed']+=1
            else:
                status='incomplete';result='*';counts['incomplete']+=1
            game.headers['Result']=result
            game.headers['Termination']=str(outcome.termination.name if outcome else status)
            stream.write(str(game)+'\n\n');stream.flush()
            record={'game':n+1,'opening_pair':n//2+1,'candidate_color':'white' if cand_color else 'black',
                    'result':status,'chess_result':result,'plies_after_seed':len(list(game.mainline_moves())),
                    'error':error}
            records.append(record)
            report={'completed_games':counts['completed'],'games_played':len(records),'counts':dict(counts),
                    'games':records,'opening_seed':args.seed}
            (args.out/'progress.json').write_text(json.dumps(report,indent=2)+'\n')
            print('TACTICAL_AB',n+1,'/',2*args.pairs,status,dict(counts),flush=True)
    completed=counts['completed']
    totals={'wins':counts['wins'],'draws':counts['draws'],'losses':counts['losses'],
            'completed':completed,'errors':counts['errors'],'incomplete':counts['incomplete'],
            'score_percent':round(100*(counts['wins']+0.5*counts['draws'])/completed,2) if completed else None}
    by_color={}
    for color in ('white','black'):
        subset=[r for r in records if r['candidate_color']==color]
        ct=Counter(r['result'] for r in subset)
        by_color[color]={'games':len(subset),'wins':ct['win'],'draws':ct['draw'],'losses':ct['loss'],
             'errors':ct['error'],'incomplete':ct['incomplete']}
    pgn=args.out/'tactical-v07-vs-native-v06.pgn'
    summary={'schema':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
       'experiment':'Candidate native tactical v0.7 vs frozen native v0.6; direct paired openings',
       'baseline_commit_sha':args.base_sha,'opening_seed':args.seed,
       'opening_fens':[p['fen'] for p in seeds],'paired_openings':args.pairs,
       'seconds_per_move':args.seconds,'max_plies_after_seed':args.max_plies,
       'candidate':totals,'candidate_by_color':by_color,
       'source_pgn_sha256':hashlib.sha256(pgn.read_bytes()).hexdigest(),
       'games':records,
       'limitations':'Two different native search strategies, same handcrafted eval, small paired test; not Elo; timed results may vary with CPU load. No automatic promotion.'}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('TACTICAL_AB_FINAL',json.dumps({k:v for k,v in summary.items() if k not in ('opening_fens','games')},indent=2),flush=True)
    if counts['errors'] or counts['incomplete']:
        raise RuntimeError(f'Invalid game completions: {dict(counts)}')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,default=ROOT/'native/bin/gm1000-native')
    p.add_argument('--baseline',type=Path,default=ROOT/'build/baseline/gm1000-baseline')
    p.add_argument('--base-sha',default='0d5568e39c643a657d669b320e9463359bab06be')
    p.add_argument('--pairs',type=int,default=16)
    p.add_argument('--seconds',type=float,default=.2)
    p.add_argument('--max-plies',type=int,default=220)
    p.add_argument('--seed',type=int,default=26103171)
    p.add_argument('--out',type=Path,default=ROOT/'reports/native-tactical-v07')
    run(p.parse_args())