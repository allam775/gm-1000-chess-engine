"""Frozen GM1000 v0.7/v0.8 validation against identical Stockfish opponents.

Skill5: 50 held-out paired openings, 100 games per version (200 total).
Skill10: *different* 30 held-out paired openings, 60 games per version (120 total).
One opening / color / engine is one slot. No learning, books, or auto promotion.
Incomplete and errored games are reported, not scored as draws.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from scripts.stockfish19_selfplay400 import varied_opening_positions

ROOT = Path(__file__).resolve().parents[1]
SHA_V08 = '043c2c2a22e854ddba30a9e05938787a68d7163f'
SHA_V09 = 'c10510c833f9736130de420bcceaf945d0f88651'
SETTINGS = {
    5: dict(seed=26103551, pairs=50, shards=5, per_shard=10),
    10: dict(seed=26103560, pairs=30, shards=3, per_shard=10),
}
SECONDS = .2
MAX_PLIES = 360


def opener_list(skill: int):
    spec = SETTINGS[skill]
    book = json.loads((ROOT / 'data/opening_book.json').read_text(encoding='utf-8'))
    pos = varied_opening_positions(book, pairs=spec['pairs'], seed=spec['seed'])
    assert len(pos) == spec['pairs']
    assert len({chess.Board(p['fen']).epd() for p in pos}) == len(pos), 'duplicate opening FEN'
    return pos


def summary_stats(rows: list[dict]):
    c = Counter(g['outcome'] for g in rows)
    complete = c['win'] + c['draw'] + c['loss']
    def sub(color):
        d = Counter(g['outcome'] for g in rows if g['color'] == color)
        n = d['win'] + d['draw'] + d['loss']
        return dict(games=sum(d.values()), completed=n, wins=d['win'], draws=d['draw'],
                    losses=d['loss'], errors=d['error'], incomplete=d['incomplete'],
                    score_percent=round(100*(d['win']+.5*d['draw'])/n,2) if n else None)
    return dict(games=len(rows),completed=complete,wins=c['win'],draws=c['draw'],
                losses=c['loss'],errors=c['error'],incomplete=c['incomplete'],
                score_percent=round(100*(c['win']+.5*c['draw'])/complete,2) if complete else None,
                by_color={color:sub(color) for color in ('white','black')})


def result_for(board: chess.Board, own_color: bool, error: str | None):
    if error: return 'error', '*', 'engine_error'
    terminal = board.outcome(claim_draw=True)
    if terminal is None: return 'incomplete','*','move_cap_incomplete'
    label = 'draw' if terminal.winner is None else 'win' if terminal.winner == own_color else 'loss'
    return label,terminal.result(),terminal.termination.name


def play_shard(args):
    spec = SETTINGS[args.skill]
    if args.shard not in range(spec['shards']): raise ValueError('shard outside range')
    if not all(path.is_file() for path in (args.v08,args.v09,args.stockfish)):
        raise FileNotFoundError('One or more pinned UCI engines are missing')
    opens = opener_list(args.skill)
    selected = opens[args.shard*spec['per_shard']:(args.shard+1)*spec['per_shard']]
    folder = args.output / f'skill{args.skill}' / f'shard-{args.shard}'
    folder.mkdir(parents=True,exist_ok=True)
    pgn_path = folder/'all-games.pgn'
    rows=[]
    with chess.engine.SimpleEngine.popen_uci(str(args.v08.resolve()),timeout=20) as v08, \
         chess.engine.SimpleEngine.popen_uci(str(args.v09.resolve()),timeout=20) as v09, \
         chess.engine.SimpleEngine.popen_uci(str(args.stockfish.resolve()),timeout=20) as sf, \
         pgn_path.open('w',encoding='utf-8') as pgn:
        id_sf = sf.id.get('name','unknown')
        sf.configure({k:v for k,v in {'Skill Level':args.skill,'Threads':1,'Hash':16,'UCI_LimitStrength':False}.items()
                      if k in sf.options})
        assert 'Skill Level' in sf.options and 'Threads' in sf.options
        engines={'v08':v08,'v09':v09}
        for local,opening in enumerate(selected):
            idx = args.shard*spec['per_shard']+local
            for color in ('white','black'):
                gm_color = chess.WHITE if color=='white' else chess.BLACK
                for version in ('v08','v09'):
                    b = chess.Board(opening['fen'])
                    g = chess.pgn.Game(); g.setup(b)
                    g.headers.update({
                      'Event':'GM1000 fresh frozen v08 vs v09 independent Stockfish control',
                      'White': f'GM1000-{version}' if gm_color else f'StockfishSkill{args.skill}',
                      'Black': f'StockfishSkill{args.skill}' if gm_color else f'GM1000-{version}',
                      'SkillLevel':str(args.skill),'GMVariant':version,'OpeningID':str(idx),
                      'OpeningSeed':str(spec['seed']),'Shard':str(args.shard),
                      'GMSourceSHA':SHA_V08 if version=='v08' else SHA_V09,
                      'TimeSeconds':str(SECONDS),'Memory':'disabled','OpponentEngine':id_sf,
                    })
                    node = g; gm=engines[version];error=None
                    # Each game gets distinct tokens for both sides: new-game UCI state.
                    tokens={gm:object(),sf:object()}
                    for ply in range(MAX_PLIES):
                        if b.is_game_over(claim_draw=True):break
                        e=gm if b.turn==gm_color else sf
                        try:
                            ans=e.play(b,chess.engine.Limit(time=SECONDS),game=tokens[e])
                            if ans.move is None or ans.move not in b.legal_moves:
                                raise RuntimeError('illegal or missing move')
                            node=node.add_variation(ans.move);b.push(ans.move)
                        except Exception as exc:
                            error=f'{type(exc).__name__}: {exc}';break
                    label,result,reason=result_for(b,gm_color,error)
                    g.headers['Result']=result;g.headers['Termination']=reason
                    pgn.write(str(g)+'\n\n');pgn.flush()
                    row=dict(skill_level=args.skill,shard=args.shard,opening_id=idx,variant=version,
                             color=color,outcome=label,result=result,termination=reason,
                             plies_after_seed=len(list(g.mainline_moves())),error=error)
                    rows.append(row)
                    progress=dict(skill=args.skill,shard=args.shard,played=len(rows),
                                  total=4*spec['per_shard'],score={v:summary_stats([r for r in rows if r['variant']==v]) for v in engines},
                                  games=rows)
                    (folder/'progress.json').write_text(json.dumps(progress,indent=2)+'\n',encoding='utf-8')
                    print('VALIDATION_GAME',args.skill,args.shard,len(rows),'/',4*spec['per_shard'],version,color,label,flush=True)
    report=dict(schema=1,created_utc=datetime.now(timezone.utc).isoformat(),
                tournament='GM1000 frozen v08 and v09 against independent Stockfish',
                skill=args.skill,shard=args.shard,seed=spec['seed'],
                variant_shas={'v08':SHA_V08,'v09':SHA_V09},
                opponent_name=id_sf,stockfish_threads=1,stockfish_hash_mb=16,
                time_seconds=SECONDS,max_plies=MAX_PLIES,
                opening_ids=list(range(args.shard*spec['per_shard'],(args.shard+1)*spec['per_shard'])),
                opening_fens=[p['fen'] for p in selected],games=rows,
                scores={v:summary_stats([r for r in rows if r['variant']==v]) for v in ('v08','v09')},
                pgn_sha256=hashlib.sha256(pgn_path.read_bytes()).hexdigest())
    (folder/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if len(rows)!=4*spec['per_shard'] or any(r['outcome'] not in ('win','draw','loss') for r in rows):
        raise RuntimeError('Invalid/incomplete shard; preserve partial and do not score')
    print('VALIDATION_SHARD_FINAL',args.skill,args.shard,json.dumps(report['scores']),flush=True)


def single_score(o):
    return {'win':1.,'draw':.5,'loss':0.}[o]


def review_pgn(pgn_path:Path,report:dict):
    assert hashlib.sha256(pgn_path.read_bytes()).hexdigest()==report['pgn_sha256'], 'PGN SHA mismatch'
    with pgn_path.open(encoding='utf-8') as stream:
        for row in report['games']:
            g=chess.pgn.read_game(stream)
            assert g is not None and not g.errors, 'Corrupt PGN'
            h=g.headers
            assert h['OpeningID']==str(row['opening_id']) and h['GMVariant']==row['variant']
            assert h['SkillLevel']==str(row['skill_level']) and h['Result']==row['result']
            b=g.board(); n=0
            for m in g.mainline_moves():
                assert m in b.legal_moves
                b.push(m);n+=1
            assert n==row['plies_after_seed']
            winner_color=chess.WHITE if row['color']=='white' else chess.BLACK
            label,result,termination=result_for(b,winner_color,None)
            assert label==row['outcome'] and result==row['result'] and termination==row['termination'], 'Wrong terminal outcome'
        assert chess.pgn.read_game(stream) is None, 'Unaccounted PGN game'


def merge_stage(args):
    spec=SETTINGS[args.skill]
    data=[]
    for i in range(spec['shards']):
        folder=args.input/f'gm1000-v09-skill{args.skill}-shard-{i}'
        path=folder/'summary.json'
        if not path.is_file():raise FileNotFoundError(path)
        d=json.loads(path.read_text(encoding='utf-8'))
        assert d['skill']==args.skill and d['shard']==i and d['seed']==spec['seed']
        assert d['variant_shas']=={'v08':SHA_V08,'v09':SHA_V09}
        assert d['time_seconds']==SECONDS and d['max_plies']==MAX_PLIES
        assert d['stockfish_threads']==1 and d['stockfish_hash_mb']==16
        assert len(d['games'])==40 and len(d['opening_fens'])==spec['per_shard']
        review_pgn(folder/'all-games.pgn',d)
        data.append(d)
    assert len({d['opponent_name'] for d in data})==1, 'Inconsistent Stockfish versions across shards'
    games=[g for d in data for g in d['games']]
    assert len(games)==spec['pairs']*4
    idx={(r['opening_id'],r['color'],r['variant']) for r in games}
    expected={(i,c,v) for i in range(spec['pairs']) for c in ('white','black') for v in ('v08','v09')}
    assert idx==expected, 'Missing or duplicate controlled game slot'
    assert all(g['outcome'] in ('win','draw','loss') for g in games)
    by_slot={(g['opening_id'],g['color'],g['variant']):g for g in games}
    # Cluster two colors by opening so precision is not overstated by paired positions.
    delta_openings=[]
    for i in range(spec['pairs']):
        diffs=[single_score(by_slot[(i,c,'v09')]['outcome'])-single_score(by_slot[(i,c,'v08')]['outcome'])
               for c in ('white','black')]
        delta_openings.append(statistics.mean(diffs))
    mean=statistics.mean(delta_openings)
    spread=1.96*statistics.stdev(delta_openings)/(len(delta_openings)**.5)
    scores={v:summary_stats([g for g in games if g['variant']==v]) for v in ('v08','v09')}
    assert all(s['completed']==spec['pairs']*2 and s['errors']==0 and s['incomplete']==0 for s in scores.values())
    result=dict(schema=1,created_utc=datetime.now(timezone.utc).isoformat(),
                study='GM1000 frozen v0.8 vs v0.9 Stockfish controlled holdout',
                skill_level=args.skill,opponent=data[0]['opponent_name'],
                matched_openings=spec['pairs'],games_per_version=spec['pairs']*2,
                total_games=len(games),time_seconds=SECONDS,
                seed=spec['seed'],versions={'v08':SHA_V08,'v09':SHA_V09},
                scores=scores,score_advantage_v09_percentage_points=round(mean*100,2),
                approximate_95pct_ci_opening_clustered_pct=[round((mean-spread)*100,2),round((mean+spread)*100,2)],
                opening_cluster_deltas=delta_openings,
                shards=[dict(shard=d['shard'],pgn_sha256=d['pgn_sha256'],scores=d['scores']) for d in data],
                games=games,
                limitations=['Same nominal time and opponent version, but weak-skill moves may be stochastic.',
                   'Normal CI is descriptive with opening clustering, not a guaranteed rating/confidence claim.',
                   'Skill Level is not a calibrated Elo rating. No engine promotion is automatic.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('VALIDATION_STAGE_FINAL',args.skill,json.dumps({k:v for k,v in result.items() if k not in ('games','opening_cluster_deltas')},indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('play')
    s.add_argument('--skill',type=int,choices=(5,10),required=True)
    s.add_argument('--shard',type=int,required=True)
    s.add_argument('--v08',type=Path,default=ROOT/'build/tournament/v08')
    s.add_argument('--v09',type=Path,default=ROOT/'build/tournament/v09')
    s.add_argument('--stockfish',type=Path,default=Path(os.environ.get('STOCKFISH_PATH','/usr/games/stockfish')))
    s.add_argument('--output',type=Path,default=ROOT/'reports/v09-independent')
    a=sub.add_parser('aggregate')
    a.add_argument('--skill',type=int,choices=(5,10),required=True)
    a.add_argument('--input',type=Path,default=ROOT/'reports/v09-independent-collected')
    a.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    (play_shard if args.action=='play' else merge_stage)(args)


if __name__=='__main__':main()