"""Recheck selected native Black mistakes with deeper independent Stockfish19 analysis.

Read authentic FEN and played UCI from the previously published forensic file.
Never assert that a first flagged error caused a game loss.
"""
from __future__ import annotations
import argparse,json,statistics
from datetime import datetime,timezone
from pathlib import Path
import chess,chess.engine
ROOT=Path(__file__).resolve().parents[1]

def evalmove(sf,b,seconds,forced=None):
    info=sf.analyse(b,chess.engine.Limit(time=seconds),
                    root_moves=[forced] if forced else None)
    score=info["score"].pov(b.turn).score(mate_score=10000)
    pv=info.get("pv") or []
    return score,pv[0] if pv else None

def run(args):
    report=json.loads((ROOT/"data/native_v06_black_forensic_summary.json").read_text())
    assert report["games"]==40 and len(report["black_loss_examples"])==10
    selected=[]
    for g in report["black_loss_examples"]:
        rows=[g["first_major"]]+[
            r for r in g["three_earliest_major"][1:] if r["cp_loss"]>=350]
        for r in rows:
            if r is None or not r.get("fen"):continue
            selected.append((g["game"],r))
    results=[]
    with chess.engine.SimpleEngine.popen_uci(args.stockfish) as sf:
        if "Stockfish 19" not in sf.id.get("name",""):
            raise RuntimeError(f"Expected Stockfish19, got {sf.id}")
        sf.configure({k:v for k,v in {"Skill Level":20,"Threads":1,"Hash":128,"UCI_LimitStrength":False}.items() if k in sf.options})
        for game,r in selected:
            b=chess.Board(r["fen"])
            move=chess.Move.from_uci(r["uci"])
            if b.turn!=chess.BLACK or move not in b.legal_moves:
                raise AssertionError(f"Invalid Black position in G{game}")
            best,bm=evalmove(sf,b,args.seconds)
            played,_=evalmove(sf,b,args.seconds,move)
            mate=abs(best)>=9000 or abs(played)>=9000
            loss=None if mate else max(0,best-played)
            if loss is None:judgement="mate-range; evaluate separately"
            elif loss<100:judgement="not confirmed at deeper search"
            elif loss<200:judgement="uncertain / moderate"
            elif best>=-200 and played<=-300:judgement="large deterioration from viable position"
            elif best<-300:judgement="already disadvantaged before this move"
            else:judgement="major loss of evaluation; causality not proved"
            result={"game":game,"ply":r["ply"],"move_number":r["move_no"],
              "played":r["san"],"played_uci":r["uci"],
              "original_short_cp_loss":r["cp_loss"],
              "best_move_deeper":b.san(bm) if bm else None,
              "best_cp":best,"played_cp":played,
              "deep_cp_loss":loss,"assessment":judgement,"fen":r["fen"]}
            results.append(result)
            print("DEEP_BLACK_REVIEW",json.dumps({k:v for k,v in result.items() if k!="fen"}),flush=True)
    first=[r for r in results if any(
        r["game"]==g["game"] and r["ply"]==g["first_major"]["ply"]
        for g in report["black_loss_examples"] if g["first_major"])]
    data={"schema":1,"generated_at":datetime.now(timezone.utc).isoformat(),
          "teacher":"Official Stockfish19 Skill20","seconds_per_root":args.seconds,
          "source":"data/native_v06_black_forensic_summary.json",
          "games_with_review":len(set(r["game"] for r in results)),
          "positions_checked":len(results),"first_major_positions":len(first),
          "confirmed_first_200cp":sum(r["deep_cp_loss"] is not None and r["deep_cp_loss"]>=200 for r in first),
          "dismissed_first_lt100cp":sum(r["deep_cp_loss"] is not None and r["deep_cp_loss"]<100 for r in first),
          "large_viable_position_deteriorations":sum(r["assessment"]=="large deterioration from viable position" for r in first),
          "positions":results,
          "limitations":["Teacher's separate best and forced root searches can vary with depth and stochastic search behavior.",
                         "1-second scores indicate useful positions for review, not causal proof or validated general improvement.",
                         "No playing engine or opponent settings were changed."]}
    out=ROOT/"data/native_v06_black_deep_review.json"
    out.write_text(json.dumps(data,indent=2)+"\n")
    print("DEEP_SUMMARY",json.dumps({k:v for k,v in data.items() if k!="positions"},indent=2),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stockfish",required=True)
    p.add_argument("--seconds",type=float,default=1.0)
    a=p.parse_args()
    if not .2<=a.seconds<=3:p.error("seconds must be in [.2,3]")
    run(a)
