"""Audit authentic 40-game GM-1000 v0.6 tournament using Stockfish 19.

Full Black games plus first 70 plies of White controls. Short independent
root scores are estimates; no move is declared causally losing solely by CPL.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,statistics
from pathlib import Path
from datetime import datetime,timezone
import chess,chess.pgn,chess.engine

ROOT=Path(__file__).resolve().parents[1]

def avg(values):
    return round(statistics.mean(values),2) if values else None

def phase(ply):
    return 'opening' if ply<=24 else 'middlegame' if ply<=70 else 'late'

def load_games(source):
    games=[]
    with source.open(encoding='utf-8') as stream:
        for i in range(1,41):
            g=chess.pgn.read_game(stream)
            if g is None or g.errors:raise AssertionError(f'Invalid or missing PGN game {i}')
            color=chess.WHITE if g.headers['White']=='native' else chess.BLACK
            assert color == (chess.WHITE if i%2 else chess.BLACK)
            assert g.headers['EngineVariant']=='native' and g.headers['SkillLevel']=='5'
            assert g.headers['Memory']=='both off' and g.headers['TimeSeconds']=='0.2'
            outcome=g.headers['Result']
            assert outcome in ('1-0','0-1','1/2-1/2')
            status=('draw' if outcome=='1/2-1/2' else
                    'win' if (outcome=='1-0')==color else 'loss')
            games.append((i,g,color,status))
        assert chess.pgn.read_game(stream) is None
    assert collections.Counter(s for _,_,c,s in games if c==chess.BLACK)=={'loss':10,'draw':5,'win':5}
    assert collections.Counter(s for _,_,c,s in games if c==chess.WHITE)=={'win':9,'draw':5,'loss':6}
    return games

def score(sf,b,seconds,move=None):
    info=sf.analyse(b,chess.engine.Limit(time=seconds),root_moves=[move] if move else None)
    return info['score'].pov(b.turn).score(mate_score=10000),(info.get('pv') or [None])[0]

def group(games):
    gm=[m for g in games for m in g['moves'] if m['ours']]
    enemy=[m for g in games for m in g['moves'] if not m['ours']]
    def stats(rows):
        eligible=[m for m in rows if m['cp_loss'] is not None]
        return {'analyzed':len(rows),'nonmate':len(eligible),'major_200cp':sum(m['cp_loss']>=200 for m in eligible),
                'median_cpl':round(statistics.median([m['cp_loss'] for m in eligible]),1) if eligible else None,
                'by_phase':{p:{'moves':len(sub:=[m for m in eligible if m['phase']==p]),
                    'major_200cp':sum(m['cp_loss']>=200 for m in sub),
                    'major_rate_pct':round(100*sum(m['cp_loss']>=200 for m in sub)/len(sub),1) if sub else None}
                    for p in ('opening','middlegame','late')}}
    return {'games':len(games),'ids':[g['game'] for g in games],'ours':stats(gm),'stockfish5':stats(enemy),
            'castled_early':sum(g['castled_early'] for g in games),
            'mean_queen_moves_first24plies':avg([g['queen_moves_first24plies'] for g in games]),
            'mean_first_major_ply':avg([g['first_major']['ply'] for g in games if g['first_major']]),
            'games_with_major':sum(bool(g['first_major']) for g in games)}

def run(args):
    games=load_games(args.pgn)
    args.out.mkdir(parents=True,exist_ok=True)
    records=[]
    with chess.engine.SimpleEngine.popen_uci(args.stockfish) as sf:
        name=sf.id.get('name','')
        if 'Stockfish 19' not in name:raise ValueError(f'Unexpected teacher: {name}')
        sf.configure({k:v for k,v in {'Skill Level':20,'Threads':1,'Hash':64,'UCI_LimitStrength':False}.items() if k in sf.options})
        for i,g,color,status in games:
            b=g.board();moves=[];queen=0;castled=False
            source_moves=list(g.mainline_moves())
            for ply,move in enumerate(source_moves,1):
                ours=b.turn==color
                if ours and ply<=24 and b.piece_type_at(move.from_square)==chess.QUEEN:queen+=1
                if ours and ply<=35 and b.is_castling(move):castled=True
                if color==chess.BLACK or ply<=70:
                    san=b.san(move);fen=b.fen()
                    best,bm=score(sf,b,args.seconds)
                    played,_=score(sf,b,args.seconds,move)
                    mate=abs(best)>=9000 or abs(played)>=9000
                    cpl=max(0,best-played) if not mate else None
                    moves.append({'ply':ply,'move_no':b.fullmove_number,'phase':phase(ply),
                        'ours':ours,'san':san,'uci':move.uci(),
                        'best_san':b.san(bm) if bm else None,'best_uci':bm.uci() if bm else None,
                        'best_cp':best,'played_cp':played,'cp_loss':cpl,'mate_related':mate,
                        'piece':chess.piece_symbol(b.piece_type_at(move.from_square)),
                        'capture':b.is_capture(move),'best_capture':b.is_capture(bm) if bm else False,
                        'fen':fen if ours and cpl is not None and cpl>=150 else None})
                b.push(move)
            errors=[m for m in moves if m['ours'] and m['cp_loss'] is not None and m['cp_loss']>=200]
            rec={'game':i,'gm_color':'white' if color else 'black','result':status,
                 'full_game_plies':len(source_moves),'analyzed_plies':len(moves),
                 'termination':g.headers.get('Termination'),
                 'start_fen':g.board().fen(), 'castled_early':castled,
                 'queen_moves_first24plies':queen,'first_major':errors[0] if errors else None,
                 'three_earliest_major':errors[:3],
                 'three_largest_major':sorted(errors,key=lambda m:-m['cp_loss'])[:3],
                 'moves':moves}
            records.append(rec)
            print(f'AUDIT G{i:02d} {rec["gm_color"]} {status} {len(moves)} plies {len(errors)} major',flush=True)
            (args.out/'progress.json').write_text(json.dumps({'games_completed':len(records),'done':[
                {'game':q['game'],'color':q['gm_color'],'result':q['result'],'first':q['first_major']}
                for q in records]},indent=2)+'\n')
    by={c:{o:group([g for g in records if g['gm_color']==c and g['result']==o])
           for o in ('win','draw','loss')} for c in ('black','white')}
    summary={'schema':1,'generated_at':datetime.now(timezone.utc).isoformat(),
       'original_run_id':41203570679,'teacher':'Stockfish 19 Skill20',
       'analysis_time_per_root':args.seconds,'source_sha256':hashlib.sha256(args.pgn.read_bytes()).hexdigest(),
       'games':len(records),'analysis_scope':'Black full games, White up to first 70 plies',
       'by_color_outcome':by,
       'black_loss_examples':[{'game':r['game'],'full_plies':r['full_game_plies'],
          'first_major':r['first_major'],'three_earliest_major':r['three_earliest_major'],
          'castled_early':r['castled_early'],'queen_moves_first24plies':r['queen_moves_first24plies']}
          for r in records if r['gm_color']=='black' and r['result']=='loss'],
       'black_wins_examples':[{'game':r['game'],'first_major':r['first_major']}
          for r in records if r['gm_color']=='black' and r['result']=='win'],
       'limitations':['Short independent root search vs forced-played search is noisy, not proof of causation.',
         'Mate-range positions excluded from centipawn mistake counts.',
         'Only Black games analyzed to completion; White control capped at 70 plies.',
         'Opening seeds start from mid-opening FENs; phase is relative to seeded starting position.',
         'Scores are not FIDE Elo and analysis makes no game-engine changes.']}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (args.out/'all_moves.json').write_text(json.dumps({'schema':1,'records':records},indent=2)+'\n')
    print('BLACK_LOSSES_COMPARISON',json.dumps(by['black'],indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pgn',type=Path,default=ROOT/'reports/native-40-source/native-matches.pgn')
    p.add_argument('--stockfish',default='/usr/games/stockfish')
    p.add_argument('--seconds',type=float,default=.035)
    p.add_argument('--out',type=Path,default=ROOT/'reports/native-black-forensic')
    args=p.parse_args()
    if not .025<=args.seconds<=.4:p.error('seconds must be .025..0.4')
    run(args)