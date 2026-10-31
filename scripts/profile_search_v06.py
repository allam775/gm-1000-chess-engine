"""Reproducible search-speed audit from archived, genuine Level-5 games.

Measures completed depth and nodes/sec with both memory systems disabled.
Uses a separate cProfile run to pinpoint Python overhead; profiling results
are not treated as normal playing speed.
"""
from __future__ import annotations
import argparse
import cProfile
import json
import pstats
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn
from engine.search import Engine

ROOT = Path(__file__).resolve().parents[1]


def sample_positions(per_game=2, max_positions=16):
    positions = []
    for tournament in range(1, 5):
        file = ROOT / f"data/skill5-original-pgn/tournament-{tournament:02d}.pgn"
        with file.open(encoding="utf-8") as stream:
            for game_no in range(1, 5):
                game = chess.pgn.read_game(stream)
                if not game or game.errors:
                    raise ValueError(f"Invalid or missing PGN: T{tournament}G{game_no}")
                length = len(list(game.mainline_moves()))
                for target_ply in (min(20,length//2), min(36,length-2)):
                    board = game.board()
                    for ply, move in enumerate(game.mainline_moves(), 1):
                        if ply > target_ply:
                            break
                        board.push(move)
                    if not board.is_game_over(claim_draw=True):
                        positions.append({"id":f"T{tournament}G{game_no}-P{target_ply}",
                                          "fen":board.fen(),"phase":"opening" if target_ply <= 20 else "middlegame"})
                    if len(positions) >= max_positions:
                        return positions
    return positions


def fresh_engine():
    engine = Engine()
    engine.own_book = False
    engine.learning_enabled = False
    engine.memory_enabled = False
    engine.stockfish_memory_enabled = False
    engine.learned_eval_enabled = False
    return engine


def benchmark(seconds=0.2, positions=None):
    positions = positions or sample_positions()
    out=[]
    for p in positions:
        board=chess.Board(p["fen"])
        engine=fresh_engine()
        start=time.perf_counter()
        result=engine.search(board, time_limit=seconds, depth=16, allow_book=False)
        wall=time.perf_counter()-start
        if result.move is not None and result.move not in board.legal_moves:
            raise AssertionError(f"Illegal returned move for {p['id']}")
        out.append({"id":p["id"],"phase":p["phase"],"depth":result.depth,
                    "nodes":result.nodes,"wall_seconds":round(wall,4),
                    "nps":round(result.nodes/max(wall,1e-6)),
                    "returned_legal_move":result.move is not None})
    return out


def hotspots(board):
    # Same evaluator but no clock; cProfile distorts measured speed, so use
    # results ONLY for relative hotspots, not NPS or Elo comparisons.
    engine=fresh_engine()
    prof=cProfile.Profile()
    prof.enable()
    result=engine.search(board,time_limit=None,depth=2,allow_book=False)
    prof.disable()
    stats=pstats.Stats(prof)
    rows=[]
    for (file,line,name),(primitive,total,own,cumulative,callers) in stats.stats.items():
        if "python-chess" not in file and "chess/" not in file and "engine/" not in file:
            continue
        rows.append({"function":f"{Path(file).name}:{line}:{name}",
                     "calls":total,"own_seconds":round(own,5),
                     "cumulative_seconds":round(cumulative,5)})
    rows.sort(key=lambda r:r["own_seconds"],reverse=True)
    return {"depth":result.depth,"nodes":result.nodes,"top_self_time":rows[:25]}


def run(seconds=0.2, n=16, out=None):
    positions=sample_positions(max_positions=n)
    rows=benchmark(seconds=seconds,positions=positions)
    profile=hotspots(chess.Board(positions[0]["fen"]))
    result={"schema":1,"created_utc":datetime.now(timezone.utc).isoformat(),
            "experiment":"GM-1000 v0.5 baseline independent search profile",
            "code_version":"main","time_limit_seconds":seconds,
            "sample_positions":len(rows),
            "median_depth":statistics.median(x["depth"] for x in rows),
            "median_nps":round(statistics.median(x["nps"] for x in rows)),
            "min_depth":min(x["depth"] for x in rows),
            "max_depth":max(x["depth"] for x in rows),
            "depth_distribution":dict(sorted(Counter(x["depth"] for x in rows).items())),
            "timed_runs":rows,"unclocked_profile":profile,
            "limitations":"Small diagnostic sample from old matches, baseline only. Profiling changes timings. No strength or Elo claim."}
    if out:
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print("SEARCH_PROFILE_V06",json.dumps(result,indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds",type=float,default=0.2)
    parser.add_argument("--positions",type=int,default=16)
    parser.add_argument("--out",type=Path,default=ROOT/"reports/search_v06_profile.json")
    a=parser.parse_args()
    if not 0.02 <= a.seconds <= 5 or not 1 <= a.positions <= 32:
        parser.error("seconds must be 0.02..5 and positions 1..32")
    run(a.seconds,a.positions,a.out)


if __name__=="__main__":
    main()
