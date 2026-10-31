"""Compare actual completed depths, not misleading raw node counts."""
import json,os,re,statistics,time
from datetime import datetime,timezone
from pathlib import Path
import chess,chess.engine
from engine.search import Engine

ROOT=Path(__file__).resolve().parents[1]
POSITIONS=[
chess.STARTING_FEN,
"r1bqkbnr/pppp1ppp/2n5/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 2 3",
"r1bqk2r/ppp2ppp/2np1n2/4p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 4 6",
"r2qk1nr/1bpnppbp/p2p2p1/1p6/3PP3/2NBBN1P/PPP2PP1/R2QK2R w KQkq - 4 8",
]
exe=os.environ["NATIVE_ENGINE"]
out=[]
for i,fen in enumerate(POSITIONS):
    board=chess.Board(fen)
    python=Engine();python.own_book=False;python.memory_enabled=False;python.stockfish_memory_enabled=False
    py=python.search(board,time_limit=.2,depth=20,allow_book=False)
    with chess.engine.SimpleEngine.popen_uci(exe) as native:
        lines=[]
        def save(info):
            if "depth" in info:lines.append(info["depth"])
        start=time.perf_counter()
        best=native.play(board,chess.engine.Limit(time=.2),info=chess.engine.INFO_ALL)
        elapsed=time.perf_counter()-start
        nd=best.info.get("depth",0)
        move=best.move
    if move not in board.legal_moves:raise AssertionError("Native illegal move")
    out.append({"case":i,"python_depth":py.depth,"python_nodes":py.nodes,
                "native_depth":nd,"native_elapsed_including_spawn":round(elapsed,4),
                "native_move":move.uci(),"python_move":py.move.uci() if py.move else None})
report={"schema":1,"timestamp_utc":datetime.now(timezone.utc).isoformat(),
 "experiment":"C++17 independent alpha-beta vs original Python search; both memories off",
 "seconds_per_move":.2,"positions":out,
 "median_python_depth":statistics.median(x["python_depth"] for x in out),
 "median_native_depth":statistics.median(x["native_depth"] for x in out),
 "limitations":"Four positions, different handcrafted evaluators; raw nodes and Elo not comparable. No promotion absent paired games."}
path=ROOT/"reports/native_v06_benchmark.json";path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
