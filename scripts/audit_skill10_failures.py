"""Forensic audit of original GM1000 v0.7/v0.8 Skill5+Skill10 PGN games.

Original games from immutable Actions run 41213837106 are analysis-only training
material, NEVER inputs or results of fresh v0.9 holdout tournaments.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,statistics
from datetime import datetime,timezone
from pathlib import Path
import chess,chess.pgn,chess.engine

ORIGIN=41213837106
SOURCES={'v07':'26cdee9b59641a24be88a8574418d9d12e25c3e0',
         'v08':'043c2c2a22e854ddba30a9e05938787a68d7163f'}
SEEDS={5:'26103351',10:'26103360'}

def analysis(sf,board,m,seconds):
    a=sf.analyse(board,chess.engine.Limit(time=seconds))
    b=sf.analyse(board,chess.engine.Limit(time=seconds),root_moves=[m])
    a_cp=a['score'].pov(board.turn).score(mate_score=10000)
    b_cp=b['score'].pov(board.turn).score(mate_score=10000)
    mv=(a.get('pv') or [None])[0]
    return {'best_cp':a_cp,'played_cp':b_cp,
           'cp_loss':None if abs(a_cp)>=9000 or abs(b_cp)>=9000 else max(0,a_cp-b_cp),
           'best_uci':mv.uci() if mv else None,
           'best_san':board.san(mv) if mv else None}

def read_original(args):
    shard=json.loads(args.summary.read_text())
    assert shard['skill']==args.level and shard['shard']==args.shard
    digest=hashlib.sha256(args.pgn.read_bytes()).hexdigest()
    assert shard['pgn_sha256']==digest
    games=[]
    with args.pgn.open(encoding='utf-8') as stream:
        while (g:=chess.pgn.read_game(stream)) is not None:
            assert not g.errors,g.errors
            version=g.headers['GMVariant']
            assert version in SOURCES and g.headers['GMSourceSHA']==SOURCES[version]
            assert g.headers['SkillLevel']==str(args.level) and g.headers['OpeningSeed']==SEEDS[args.level]
            assert g.headers['TimeSeconds']=='0.2' and g.headers['Memory']=='disabled'
            color=chess.WHITE if g.headers['White']==f'GM1000-{version}' else chess.BLACK
            assert g.headers['Black' if color else 'White']==f'StockfishSkill{args.level}'
            actual=g.end().board().outcome(claim_draw=True)
            assert actual and actual.result()==g.headers['Result']
            status='draw' if actual.winner is None else 'win' if actual.winner==color else 'loss'
            row={'version':version,'color':'white' if color else 'black','opening':int(g.headers['OpeningID']),
                 'outcome':status,'game':g,'ply_count':len(list(g.mainline_moves()))}
            games.append(row)
    assert len(games)==40 and len([x for x in games if x['version']=='v08'])==20
    expected=collections.Counter((r['opening_id'],r['variant'],r['color'],r['outcome']) for r in shard['games'])
    seen=collections.Counter((r['opening'],r['version'],r['color'],r['outcome']) for r in games)
    assert expected==seen,'PGN and original report mismatch'
    return games,digest

def summarize(records):
    data=[m for g in records for m in g['moves'] if m['cp_loss'] is not None]
    by_phase={}
    for name,criteria in [('opening',lambda x:x['fullmove']<=15),('middlegame',lambda x:15<x['fullmove']<=40),('endgame',lambda x:x['fullmove']>40)]:
        subset=[m for m in data if criteria(m)]
        by_phase[name]={'checked':len(subset),'major200':sum(m['cp_loss']>=200 for m in subset),
                        'major_rate':round(100*sum(m['cp_loss']>=200 for m in subset)/len(subset),2) if subset else None}
    return {'games':len(records),'moves':len(data),'major200':sum(m['cp_loss']>=200 for m in data),
            'median_cpl':round(statistics.median(m['cp_loss'] for m in data),2) if data else None,
            'phase':by_phase}

def run(args):
    games,digest=read_original(args)
    args.out.mkdir(parents=True,exist_ok=True)
    answers=[]; confirmed=[]
    with chess.engine.SimpleEngine.popen_uci(args.stockfish,timeout=30) as sf:
        teacher=sf.id.get('name','')
        assert 'Stockfish' in teacher
        sf.configure({k:v for k,v in {'Skill Level':20,'UCI_LimitStrength':False,'Threads':1,'Hash':96}.items() if k in sf.options})
        for g in games:
            b=g['game'].board();candidate=g['version']=='v08';ours=(g['color']=='white')
            moves=[]
            for ply,move in enumerate(g['game'].mainline_moves(),1):
                if b.turn==ours:
                    # Analyze all v0.8 draws/losses, controls first 30 post-seed plies.
                    inspect=(candidate and g['outcome']!='win') or ply<=30
                    if inspect:
                        note=analysis(sf,b,move,args.seconds)
                        moves.append({'ply':ply,'fullmove':b.fullmove_number,'san':b.san(move),'uci':move.uci(),
                             'fen':b.fen() if note['cp_loss'] is not None and note['cp_loss']>=150 else None,
                             'capture':b.is_capture(move),'check':b.gives_check(move),**note})
                b.push(move)
            first=next((x for x in moves if x['cp_loss'] is not None and x['cp_loss']>=200),None)
            eligible=[x for x in moves if x['fen'] and x['cp_loss']>=220 and x['fullmove']<=45]
            if candidate and g['outcome']!='win':
                pick=[]
                if first and first['fen']:pick.append(first)
                if eligible:
                    largest=max(eligible,key=lambda x:x['cp_loss'])
                    if largest not in pick:pick.append(largest)
                for item in pick:
                    pos=chess.Board(item['fen']); forced=chess.Move.from_uci(item['uci'])
                    checked=analysis(sf,pos,forced,args.deep_seconds)
                    confirmed.append({'level':args.level,'shard':args.shard,'opening':g['opening'],
                         'color':g['color'],'outcome':g['outcome'],'ply':item['ply'],'san':item['san'],
                         'capture':item['capture'],'check':item['check'],
                         'fen':item['fen'],'short_cpl':item['cp_loss'],
                         'deeper':checked,'confirmed_major':checked['cp_loss'] is not None and checked['cp_loss']>=200,
                         'viable_before':checked['best_cp']>=-150})
            rec={k:v for k,v in g.items() if k!='game'}
            rec['moves']=moves;rec['first_major']=first and {k:v for k,v in first.items() if k!='fen'}
            answers.append(rec)
            print('AUDIT',args.level,args.shard,rec['version'],rec['color'],rec['outcome'],
                  'checked',len(moves),'first',first['san'] if first else '-',flush=True)
            (args.out/'progress.json').write_text(json.dumps({'analyzed':len(answers),'total':len(games),
                'latest':{k:v for k,v in rec.items() if k!='moves'}},indent=2)+'\n')
    groups={}
    for version in ('v07','v08'):
        for outcome in ('win','draw','loss'):
            for color in ('white','black'):
                key=f'{version}_{outcome}_{color}'
                groups[key]=summarize([r for r in answers if r['version']==version and r['outcome']==outcome and r['color']==color])
    report={'schema':1,'source_run':ORIGIN,'level':args.level,'shard':args.shard,
            'created_utc':datetime.now(timezone.utc).isoformat(),'teacher':teacher,'original_sha256':digest,
            'verified_games':40,'v08_loss_draw_games':sum(r['version']=='v08' and r['outcome']!='win' for r in answers),
            'games':[{**{k:v for k,v in x.items() if k!='moves'},'selected_errors':[m for m in x['moves'] if m['cp_loss'] is not None and m['cp_loss']>=200][:4]} for x in answers],
            'groups':groups,'deep_checks':confirmed,
            'limits':'Full-strength Stockfish post-game estimates: short best/forced root analyses are noisy; only deeper checks >=200cp are confirmed. Original PGNs reused as diagnostic set, never validation set.'}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('AUDIT_FINISHED',args.level,args.shard,'strong checks',len(confirmed),'confirmed',sum(x['confirmed_major'] for x in confirmed),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--level',type=int,choices=(5,10),required=True)
    p.add_argument('--shard',type=int,required=True)
    p.add_argument('--pgn',type=Path,required=True)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--stockfish',default='/usr/games/stockfish')
    p.add_argument('--seconds',type=float,default=.08)
    p.add_argument('--deep-seconds',type=float,default=.6)
    run(p.parse_args())