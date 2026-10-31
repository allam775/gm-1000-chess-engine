"""Frozen four-arm audit-correction tournament. Wins/scheduled games is primary.
No candidate promotion; archives errors/incompletes and every move's elapsed time.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import random
import statistics
import time

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
SHAS = {
    'v08': '043c2c2a22e854ddba30a9e05938787a68d7163f',
    'v10': 'a65726cba4ff28eaee581f9e11fca05820b644f7',
    'see': '9fed02ad37f7f82096755056164005379821e742',
    'both': 'fa0925956188518134ed081de69cb3543753b03d',
}
SECONDS = .2
SHARDS = 10
PAIRS = 50
MAX_PLIES = 400
SF_SHA256 = '7fecbc0b26454b62be5e3b237b58dc5666401b56e520aeb1b0bf8f53fa8f2ef3'
MANIFEST = ROOT / 'data/v11_audit_openings.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def openings():
    d = json.loads(MANIFEST.read_text())
    assert len(d['openings']) == PAIRS
    keys = [' '.join(x['fen'].split()[:4]) for x in d['openings']]
    assert len(set(keys)) == PAIRS and not set(keys) & set(d['excluded_fen_keys'])
    return d['openings']


def stats(rows):
    c = Counter(x['outcome'] for x in rows)
    n = len(rows)
    return dict(scheduled=n, wins=c['win'], draws=c['draw'], losses=c['loss'],
                errors=c['error'], incomplete=c['incomplete'],
                win_percent=100*c['win']/n if n else None,
                score_percent=100*(c['win']+.5*c['draw'])/n if n else None)


def outcome(board, own_color, error=None):
    if error:
        return 'error', '*', 'engine_error'
    result = board.outcome(claim_draw=True)
    if result is None:
        return 'incomplete', '*', 'move_cap_incomplete'
    label = 'draw' if result.winner is None else 'win' if result.winner == own_color else 'loss'
    return label, result.result(), result.termination.name


def play(args):
    assert 0 <= args.shard < SHARDS
    binaries = {v: args.engines/v for v in SHAS}
    assert digest(args.stockfish) == SF_SHA256, 'Opponent binary does not match pinned official 17.1 release'
    provenance = json.loads((args.engines/'provenance.json').read_text())
    assert provenance['shas'] == SHAS
    assert provenance['binary_sha256'] == {v:digest(p) for v,p in binaries.items()}
    folder = args.output/f'shard-{args.shard}'
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    pairs = openings()[args.shard*5:(args.shard+1)*5]
    with ExitStack() as stack:
        engines = {v:stack.enter_context(chess.engine.SimpleEngine.popen_uci(str(p.resolve()), timeout=10)) for v,p in binaries.items()}
        sf = stack.enter_context(chess.engine.SimpleEngine.popen_uci(str(args.stockfish.resolve()), timeout=10))
        assert sf.id['name'] == 'Stockfish 17.1'
        sf.configure({'Skill Level':5,'Threads':1,'Hash':16,'UCI_LimitStrength':False})
        pgn = stack.enter_context((folder/'all-games.pgn').open('w'))
        moves_file = stack.enter_context((folder/'moves.jsonl').open('w'))
        for opening in pairs:
            for color in [chess.WHITE, chess.BLACK]:
                # Balance order effects reproducibly; SF weak-skill randomness remains uncontrolled.
                variants = list(SHAS)
                random.Random(26105111+opening['id']*2+int(color)).shuffle(variants)
                for version in variants:
                    board = chess.Board(opening['fen'])
                    game = chess.pgn.Game();game.setup(board)
                    own = engines[version]
                    tokens = {own:object(), sf:object()}
                    game_id = f"{opening['id']}-{int(color)}-{version}"
                    game.headers.update(Event='GM1000 v11 audit corrections four-arm holdout',
                        White=version if color else 'StockfishSkill5', Black='StockfishSkill5' if color else version,
                        GMVariant=version, GMSourceSHA=SHAS[version], OpeningID=str(opening['id']),
                        SkillLevel='5', TimeSeconds=str(SECONDS), OpponentEngine=sf.id['name'],
                        OpponentSHA256=SF_SHA256, GameID=game_id, Memory='disabled')
                    node=game;error=None
                    for ply in range(MAX_PLIES):
                        if board.is_game_over(claim_draw=True):break
                        engine = own if board.turn == color else sf
                        side = version if engine is own else 'stockfish'
                        start=time.perf_counter()
                        try:
                            ans=engine.play(board,chess.engine.Limit(time=SECONDS),game=tokens[engine],info=chess.engine.INFO_ALL)
                            elapsed=time.perf_counter()-start
                            if ans.move is None or ans.move not in board.legal_moves:raise RuntimeError('illegal/missing move')
                            row=dict(game_id=game_id,ply=ply,engine=side,elapsed_seconds=elapsed,
                                requested_seconds=SECONDS,move=ans.move.uci(),depth=ans.info.get('depth'),
                                nodes=ans.info.get('nodes'),reported_time=ans.info.get('time'))
                            moves_file.write(json.dumps(row)+'\n');moves_file.flush()
                            node=node.add_variation(ans.move);board.push(ans.move)
                        except Exception as exc:
                            error=f'{type(exc).__name__}: {exc}';break
                    label,result,reason=outcome(board,color,error)
                    game.headers.update(Result=result,Termination=reason)
                    pgn.write(str(game)+'\n\n');pgn.flush()
                    rows.append(dict(game_id=game_id,opening_id=opening['id'],variant=version,
                        color='white' if color else 'black',outcome=label,result=result,termination=reason,
                        plies=len(board.move_stack),error=error))
                    (folder/'progress.json').write_text(json.dumps(dict(games=rows,
                        scores={v:stats([x for x in rows if x['variant']==v]) for v in SHAS}),indent=2))
                    print('GAME',args.shard,len(rows),version,label,flush=True)
    summary=dict(shard=args.shard,versions=SHAS,games=rows,seconds=SECONDS,
        manifest_sha256=digest(MANIFEST),opponent_sha256=SF_SHA256,provenance=provenance,
        pgn_sha256=digest(folder/'all-games.pgn'),moves_sha256=digest(folder/'moves.jsonl'),
        platform=platform.platform(),created_utc=datetime.now(timezone.utc).isoformat())
    (folder/'summary.json').write_text(json.dumps(summary,indent=2))
    assert len(rows)==40 and all(x['outcome'] in ('win','draw','loss') for x in rows), 'Incomplete shard: preserve data; do not silently score'


def verify_shard(folder, shard):
    d=json.loads((folder/'summary.json').read_text())
    assert d['shard']==shard and d['versions']==SHAS and d['seconds']==SECONDS
    assert d['manifest_sha256']==digest(MANIFEST) and d['opponent_sha256']==SF_SHA256
    assert d['pgn_sha256']==digest(folder/'all-games.pgn') and d['moves_sha256']==digest(folder/'moves.jsonl')
    telemetry=[json.loads(x) for x in (folder/'moves.jsonl').read_text().splitlines()]
    by_game={}
    for row in telemetry:by_game.setdefault(row['game_id'],[]).append(row)
    seeds={x['id']:x['fen'] for x in openings()}
    with (folder/'all-games.pgn').open() as stream:
        for row in d['games']:
            g=chess.pgn.read_game(stream);assert g and not g.errors
            assert g.headers['GameID']==row['game_id'] and g.headers['GMVariant']==row['variant']
            assert g.headers['GMSourceSHA']==SHAS[row['variant']] and g.headers['OpponentSHA256']==SF_SHA256
            assert g.headers['OpeningID']==str(row['opening_id']) and g.board().fen()==seeds[row['opening_id']]
            assert g.headers['TimeSeconds']==str(SECONDS) and g.headers['SkillLevel']=='5'
            board=g.board();moves=list(g.mainline_moves());trace=by_game.pop(row['game_id'],[])
            assert len(trace)==len(moves)==row['plies']
            for ply,(m,t) in enumerate(zip(moves,trace)):
                own_color=row['color']=='white'
                assert m in board.legal_moves and t['ply']==ply and t['move']==m.uci()
                assert t['engine']==(row['variant'] if board.turn==own_color else 'stockfish')
                assert t['elapsed_seconds']>0 and t['requested_seconds']==SECONDS
                board.push(m)
            label,result,reason=outcome(board,row['color']=='white',row['error'])
            assert (label,result,reason)==(row['outcome'],row['result'],row['termination'])
            assert result==g.headers['Result'] and reason==g.headers['Termination']
        assert chess.pgn.read_game(stream) is None and not by_game
    return d,telemetry


def aggregate(args):
    data=[];telemetry=[]
    for shard in range(SHARDS):
        d,t=verify_shard(args.input/f'gm1000-v11-shard-{shard}',shard)
        data.append(d);telemetry.extend(t)
    rows=[x for d in data for x in d['games']]
    slots=[(x['opening_id'],x['color'],x['variant']) for x in rows]
    expected={(i,c,v) for i in range(PAIRS) for c in ('white','black') for v in SHAS}
    assert len(slots)==400 and set(slots)==expected
    assert all(x['outcome'] in ('win','draw','loss') for x in rows)
    # Versions and compiled source/header fingerprints must agree across runners.
    assert all(d['provenance']['source_sha256']==data[0]['provenance']['source_sha256'] for d in data)
    assert all(d['provenance']['header_sha256']==data[0]['provenance']['header_sha256'] for d in data)
    scores={v:stats([x for x in rows if x['variant']==v]) for v in SHAS}
    by_slot={(x['opening_id'],x['color'],x['variant']):x for x in rows}
    comparisons={}
    for candidate,base in [('see','v10'),('both','see'),('both','v08'),('both','v10')]:
        delta=[statistics.mean(int(by_slot[(i,c,candidate)]['outcome']=='win')-
                               int(by_slot[(i,c,base)]['outcome']=='win') for c in ('white','black')) for i in range(PAIRS)]
        mean=statistics.mean(delta);width=1.96*statistics.stdev(delta)/(PAIRS**.5)
        comparisons[f'{candidate}-vs-{base}']=dict(win_difference_pp=100*mean,
            approximate_opening_clustered_95pct_interval_pp=[100*(mean-width),100*(mean+width)])
    timing={}
    for v in [*SHAS,'stockfish']:
        ts=[x['elapsed_seconds'] for x in telemetry if x['engine']==v]
        timing[v]=dict(moves=len(ts),median=statistics.median(ts),max=max(ts),
            over_210ms=sum(t>.210 for t in ts),over_250ms=sum(t>.250 for t in ts),over_1s=sum(t>1 for t in ts))
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),total_games=len(rows),
        games_per_variant=100,scores=scores,comparisons=comparisons,timing=timing,versions=SHAS,
        opponent='Stockfish 17.1',opponent_sha256=SF_SHA256,seconds=SECONDS,
        observed_90wins_met={v:s['wins']>=90 for v,s in scores.items()},automatic_promotion=False,
        limitations=['Nominal fixed-movetime; wall latency includes IPC and scheduling; no 200ms forfeit rule.',
          'Weak-skill opponent is stochastic; paired openings do not force identical opponent moves.',
          'Intervals are descriptive opening-clustered normal approximations, not multiplicity-adjusted guarantees.',
          'The same opening-book graph is used, but manifest excludes known prior tournament seed positions.',
          'Observed 90/100 would not establish a true underlying win probability of at least 90%.'],
        games=rows,shards=[dict(shard=d['shard'],pgn_sha256=d['pgn_sha256'],moves_sha256=d['moves_sha256']) for d in data])
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('games','shards')},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='action',required=True)
    a=subs.add_parser('play');a.add_argument('--shard',type=int,required=True)
    a.add_argument('--engines',type=Path,default=ROOT/'build/v11')
    a.add_argument('--stockfish',type=Path,required=True)
    a.add_argument('--output',type=Path,default=ROOT/'reports/v11')
    a=subs.add_parser('aggregate');a.add_argument('--input',type=Path,default=ROOT/'reports/v11-collected')
    a.add_argument('--output',type=Path,default=ROOT/'reports/v11-final.json')
    args=p.parse_args();(play if args.action=='play' else aggregate)(args)


if __name__=='__main__':main()
