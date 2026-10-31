"""Authenticate source PGNs and independently audit all v0.7 Skill-5 losses.

The original games are immutable GitHub Actions artifacts, read from run
41209206000. Stockfish 19 is a separate FULL-STRENGTH post-game analyst;
the match opponent was Stockfish Skill 5 at 0.2s per move.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import chess
import chess.engine
import chess.pgn

ROOT=Path(__file__).resolve().parents[1]
MATCH_RUN=41209206000
V06_SHA='0d5568e39c643a657d669b320e9463359bab06be'
V07_SHA='26cdee9b59641a24be88a8574418d9d12e25c3e0'
SEED='26103182'


def phase(ply: int)->str:
    return 'opening' if ply<=24 else ('middlegame' if ply<=70 else 'late')


def outcome_from_pgn(g: chess.pgn.Game, our_color: chess.Color)->str:
    r=g.headers['Result']
    if r=='1/2-1/2':return 'draw'
    if r not in ('1-0','0-1'): raise AssertionError(f'Invalid decisive result {r}')
    return 'win' if (r=='1-0')==bool(our_color) else 'loss'


def validate_games(source:Path, shard:int, expected_sha:str):
    data=source.read_bytes()
    actual_sha=hashlib.sha256(data).hexdigest()
    assert actual_sha==expected_sha,(shard,actual_sha,expected_sha)
    games=[]; seen=set()
    with source.open('r',encoding='utf-8') as f:
        for idx in range(40):
            game=chess.pgn.read_game(f)
            assert game is not None and not game.errors,('missing or illegal PGN',shard,idx,game.errors if game else None)
            h=game.headers
            assert h['Shard']==str(shard) and h['OpponentSkill']=='5'
            assert h['OpeningSeed']==SEED and h['Memories']=='disabled'
            assert h['GMTimeSeconds']=='0.2' and h['OpponentTimeSeconds']=='0.2'
            version=h['EngineVersion'];assert version in ('v06','v07')
            assert h['GMSourceSHA']==(V07_SHA if version=='v07' else V06_SHA)
            assert h['Termination'] in ('CHECKMATE','THREEFOLD_REPETITION','INSUFFICIENT_MATERIAL','FIFTY_MOVES','STALEMATE','SEVENTYFIVE_MOVES','FIVEFOLD_REPETITION')
            opening=int(h['OpeningPair']);assert shard*10<=opening<(shard+1)*10
            our_color=chess.WHITE if h['White']==f'GM1000-{version}' else chess.BLACK
            assert (h['Black'] if our_color else h['White'])=='StockfishSkill5'
            key=(opening,version,'white' if our_color else 'black')
            assert key not in seen,key
            seen.add(key)
            b=game.end().board()
            outcome=b.outcome(claim_draw=True)
            assert outcome is not None and outcome.result()==h['Result'],('final result inconsistent with legal board',key,h['Result'],outcome)
            assert outcome.termination.name==h['Termination'],('termination mismatch',key,h['Termination'],outcome.termination.name)
            games.append({'game':game,'version':version,'opening_id':opening,'color':'white' if our_color else 'black',
                          'outcome':outcome_from_pgn(game,our_color),'plies':len(list(game.mainline_moves()))})
        assert chess.pgn.read_game(f) is None,'extra games in PGN'
    assert len(games)==40 and len(seen)==40
    assert sum(g['version']=='v07' for g in games)==20
    return games,actual_sha


def score_root(sf, board, seconds, played=None):
    info=sf.analyse(board,chess.engine.Limit(time=seconds),root_moves=[played] if played is not None else None)
    score=info['score'].pov(board.turn).score(mate_score=10000)
    moves=info.get('pv') or []
    return score,(moves[0] if moves else None)


def eval_position(sf, board, played, seconds):
    best,bestmove=score_root(sf,board,seconds)
    playedscore,_=score_root(sf,board,seconds,played)
    mate=abs(best)>=9000 or abs(playedscore)>=9000
    return dict(best_cp=best,played_cp=playedscore,
                cp_loss=None if mate else max(0,best-playedscore),
                mate_related=mate,best_uci=bestmove.uci() if bestmove else None,
                best_san=board.san(bestmove) if bestmove else None)


def stat_group(rows):
    eligible=[r for r in rows if r['cp_loss'] is not None]
    def stats(data):
        return dict(positions=len(data),major_200cp=sum(x['cp_loss']>=200 for x in data),
                    major_rate_percent=round(100*sum(x['cp_loss']>=200 for x in data)/len(data),2) if data else None,
                    mean_cpl=round(statistics.mean(x['cp_loss'] for x in data),1) if data else None,
                    median_cpl=round(statistics.median(x['cp_loss'] for x in data),1) if data else None)
    return dict(all_checked=len(rows),nonmate=stats(eligible),
                by_phase={p:stats([r for r in eligible if r['phase']==p]) for p in ('opening','middlegame','late')})


def run(args):
    shard=args.shard
    shard_report=json.loads(args.shard_summary.read_text())
    source=args.pgn
    assert shard_report['shard']==shard
    games,source_sha=validate_games(source,shard,shard_report['pgn_sha256'])
    # Verify all original PGN classifications against independent machine-readable scorecard.
    tuples=Counter((x['opening_id'],x['version'],x['color'],x['outcome']) for x in games)
    expected=Counter((x['opening_id'],x['variant'],x['color'],x['outcome']) for x in shard_report['games'])
    assert tuples==expected,('PGNs disagree with original report',shard,tuples-expected,expected-tuples)
    args.out.mkdir(parents=True,exist_ok=True)
    all_reports=[]; deep_checked=[]; teacher=''
    with chess.engine.SimpleEngine.popen_uci(str(args.stockfish),timeout=30) as sf:
        teacher=sf.id.get('name','')
        assert teacher.startswith('Stockfish 19'),('teacher not Stockfish19',teacher)
        sf.configure({k:v for k,v in {'Skill Level':20,'UCI_LimitStrength':False,'Threads':1,'Hash':96}.items() if k in sf.options})
        for index, rec in enumerate(games):
            if rec['version']!='v07':continue
            game=rec['game'];ours=chess.WHITE if rec['color']=='white' else chess.BLACK
            board=game.board();moves=[];our_count=0;first_bad=None
            for ply,move in enumerate(game.mainline_moves(),start=1):
                if board.turn==ours:
                    our_count+=1
                    # Every move of every loss; matched first 24 per side (48 plies) for all wins/draws.
                    if rec['outcome']=='loss' or ply<=args.control_plies:
                        fen=board.fen();san=board.san(move)
                        raw=eval_position(sf,board,move,args.seconds)
                        row={'ply':ply,'fullmove_number':board.fullmove_number,'phase':phase(ply),
                             'san':san,'uci':move.uci(),**raw,
                             'fen':fen if rec['outcome']=='loss' and raw['cp_loss'] is not None and raw['cp_loss']>=140 else None,
                             'piece':chess.piece_symbol(board.piece_type_at(move.from_square)),
                             'capture':board.is_capture(move),
                             'best_is_capture':board.is_capture(chess.Move.from_uci(raw['best_uci'])) if raw['best_uci'] else False}
                        moves.append(row)
                        if first_bad is None and raw['cp_loss'] is not None and raw['cp_loss']>=200:
                            first_bad=row
                board.push(move)
            output=dict(shard=shard,opening_id=rec['opening_id'],color=rec['color'],outcome=rec['outcome'],
                        game_plies=rec['plies'],total_our_moves=our_count,checked_moves=len(moves),
                        first_major_200cp=first_bad,
                        top_three_errors=sorted((r for r in moves if r['cp_loss'] is not None),key=lambda x:-x['cp_loss'])[:3],
                        errors_200cp=sum(r['cp_loss'] is not None and r['cp_loss']>=200 for r in moves),
                        moves=moves)
            all_reports.append(output)
            print('LOSS_AUDIT',shard,rec['opening_id'],rec['color'],rec['outcome'],
                  'checked',len(moves),'major',output['errors_200cp'],flush=True)
            (args.out/'progress.json').write_text(json.dumps({'verified_v07_games':len(all_reports),'losses_analyzed':sum(g['outcome']=='loss' for g in all_reports),
                     'games':[{'opening_id':g['opening_id'],'color':g['color'],'outcome':g['outcome'],
                                'first_major':g['first_major_200cp']} for g in all_reports]},indent=2)+'\n')
        # Deeper recheck of first major and worst other early errors for the LOSSES ONLY.
        for g in all_reports:
            if g['outcome']!='loss':continue
            choices=[]
            initial=g['first_major_200cp']
            if initial is not None:choices.append(initial)
            others=[m for m in g['moves'] if m['fen'] and m['ply']<=70 and m is not initial and m['cp_loss']>=220]
            if others:choices.append(max(others,key=lambda r:r['cp_loss']))
            for m in choices:
                board=chess.Board(m['fen']);forced=chess.Move.from_uci(m['uci'])
                assert forced in board.legal_moves
                evidence=eval_position(sf,board,forced,args.deep_seconds)
                deep_checked.append(dict(shard=shard,opening_id=g['opening_id'],color=g['color'],
                                         ply=m['ply'],san=m['san'],short_cp_loss=m['cp_loss'],
                                         deeper=evidence,fen=m['fen'],
                                         before_position_was_viable=(evidence['best_cp']>=-200 and evidence['best_cp']<9000),
                                         still_major=bool(evidence['cp_loss'] is not None and evidence['cp_loss']>=200)))
                print('LOSS_DEEP',shard,g['opening_id'],g['color'],m['ply'],m['san'],
                      'short',m['cp_loss'],'deep',evidence['cp_loss'],flush=True)
    buckets={}
    for color in ('white','black'):
        for outcome in ('loss','win','draw'):
            group=[g for g in all_reports if g['color']==color and g['outcome']==outcome]
            stat=stat_group([m for g in group for m in g['moves']])
            stat['games']=len(group);stat['games_with_major']=sum(g['first_major_200cp'] is not None for g in group)
            buckets[f'{color}_{outcome}']=stat
    compact=[{'shard':g['shard'],'opening_id':g['opening_id'],'color':g['color'],'outcome':g['outcome'],
              'game_plies':g['game_plies'],'checked_moves':g['checked_moves'],'errors_200cp':g['errors_200cp'],
              'first_major_200cp':g['first_major_200cp'],'top_three_errors':g['top_three_errors']}
             for g in all_reports if g['outcome']=='loss']
    report={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
            'original_run_id':MATCH_RUN,'source_pgn_sha256':source_sha,'shard':shard,
            'verified_games':len(games),'verified_v07_games':len(all_reports),
            'v07_loss_count':len(compact),'teacher':teacher,'short_search_seconds_per_root':args.seconds,
            'deep_search_seconds_per_root':args.deep_seconds,
            'controls_checked_first_plies':args.control_plies,
            'by_color_outcome':buckets,
            'losses':compact,'deep_checks':deep_checked,
            'limitations':['The original opponent was Stockfish Skill Level 5, not Stockfish version 5.',
              'Short best-root versus forced-root analysis is noisy; independent deeper check is the higher-confidence measure.',
              'Full losses analyzed, but wins/draws truncated at a matched opening+early middlegame horizon. Compare by identical phases.',
              'A late blunder in an already lost position may not have caused the loss.',
              '50 curated varied opening FENs may have initial advantages; PGN legality verifies game outcomes, not opening parity.',
              'No engine evaluation, search code or weights changed during audit.']}
    (args.out/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.out/'all_moves.json').write_text(json.dumps({'shard':shard,'games':all_reports},indent=2)+'\n')
    print('SHARD_VERIFIED',shard,'losses',len(compact),'deep_checked',len(deep_checked),'teacher',teacher,flush=True)
    return report


def aggregate(args):
    reports=[json.loads((args.inputs/f'shard-{i}'/'audit.json').read_text()) for i in range(5)]
    assert [r['shard'] for r in reports]==list(range(5))
    assert len({r['source_pgn_sha256'] for r in reports})==5
    assert all(r['verified_games']==40 and r['verified_v07_games']==20 for r in reports)
    assert sum(r['v07_loss_count'] for r in reports)==30
    losses=[x for r in reports for x in r['losses']]
    deeper=[x for r in reports for x in r['deep_checks']]
    assert len({(l['opening_id'],l['color']) for l in losses})==30
    by_color_outcome={}
    for color in ('white','black'):
        for outcome in ('loss','win','draw'):
            key=f'{color}_{outcome}'
            children=[r['by_color_outcome'][key] for r in reports]
            phases={}
            for phase_key in ('opening','middlegame','late'):
                sub=[q['by_phase'][phase_key] for q in children]
                n=sum(x['positions'] for x in sub)
                k=sum(x['major_200cp'] for x in sub)
                phases[phase_key]={'positions':n,'major_200cp':k,'major_rate_percent':round(100*k/n,2) if n else None}
            by_color_outcome[key]={'games':sum(x['games'] for x in children),
                'games_with_major':sum(x['games_with_major'] for x in children),
                'opening_and_phase_rates':phases,
                'all_nonmate_checked':sum(x['nonmate']['positions'] for x in children),
                'all_major_200cp':sum(x['nonmate']['major_200cp'] for x in children)}
    data={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
          'verified_total_source_games':sum(r['verified_games'] for r in reports),
          'verified_v07_games':100,'verified_v07_losses':len(losses),
          'verified_v07_loss_colors':dict(Counter(x['color'] for x in losses)),
          'source_run_id':MATCH_RUN,'origin_source_hashes':{str(r['shard']):r['source_pgn_sha256'] for r in reports},
          'stockfish_teacher':reports[0]['teacher'],
          'short_search_seconds_per_root':reports[0]['short_search_seconds_per_root'],
          'deep_search_seconds_per_root':reports[0]['deep_search_seconds_per_root'],
          'by_color_outcome':by_color_outcome,
          'deep_positions_checked':len(deeper),
          'deep_major_confirmed':sum(x['still_major'] for x in deeper),
          'deep_first_major_confirmed':sum(x['still_major'] for x in deeper if x['ply']==next((l['first_major_200cp']['ply'] for l in losses if l['opening_id']==x['opening_id'] and l['color']==x['color'] and l['first_major_200cp']),-1)),
          'deep_checks':deeper,'losses':losses,
          'limitations':reports[0]['limitations']}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,indent=2)+'\n')
    print('VERIFIED_200_AUDIT',json.dumps({k:v for k,v in data.items() if k not in ('deep_checks','losses')},indent=2),flush=True)


def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('shard')
    s.add_argument('--shard',type=int,required=True,choices=range(5))
    s.add_argument('--pgn',type=Path,required=True)
    s.add_argument('--shard-summary',type=Path,required=True)
    s.add_argument('--stockfish',type=Path,required=True)
    s.add_argument('--seconds',type=float,default=.07)
    s.add_argument('--deep-seconds',type=float,default=1.0)
    s.add_argument('--control-plies',type=int,default=48)
    s.add_argument('--out',type=Path,required=True)
    a=sub.add_parser('aggregate')
    a.add_argument('--inputs',type=Path,required=True)
    a.add_argument('--out',type=Path,default=ROOT/'data/native_v07_skill5_losses_forensic.json')
    args=p.parse_args()
    if args.command=='shard':
        assert 0.02<=args.seconds<=0.4 and .3<=args.deep_seconds<=3 and args.control_plies>=24
        run(args)
    else:aggregate(args)

if __name__=='__main__':main()