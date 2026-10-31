"""Four fixed-setting mini-tournaments vs Stockfish Skill 0.

Run two memory-enabled and two memory-disabled four-game tournaments.
The outcomes are a small-sample descriptive comparison, NOT an Elo estimate.
No learning parameters or historic position memory are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.arena import run as arena_run


def run(args):
    if args.skill != 0:
        raise ValueError("This is specifically a Skill Level 0 experiment")
    if args.games_per_tournament != 4 or args.tournaments != 4:
        raise ValueError("Experiment requires 4 tournaments of 4 games each")
    if args.seconds_per_move < .02:
        raise ValueError("Time per move must be at least .02 seconds")
    memory_file = ROOT / "data" / "position_memory.json"
    if not memory_file.exists():
        raise FileNotFoundError("Expected persisted grandmaster position memory")
    memory_bytes = memory_file.read_bytes()
    memory = json.loads(memory_bytes)
    if (memory.get("schema") != 1 or memory.get("source_games") != 560
            or memory.get("positions_count") < 32233):
        raise AssertionError("Unexpected or missing 560-GM-game position-memory snapshot")
    snapshot_sha = hashlib.sha256(memory_bytes).hexdigest()
    report_root = args.output_dir
    report_root.mkdir(parents=True, exist_ok=True)
    stockfish_path = args.stockfish or os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    if not stockfish_path and Path("/usr/games/stockfish").exists():
        stockfish_path = "/usr/games/stockfish"
    if not stockfish_path:
        raise FileNotFoundError("Stockfish executable not found")

    rounds = []
    # Two memory-on rounds and two identical-setting memory-off controls.
    for index, enabled in enumerate((True, False, True, False), 1):
        cfg = SimpleNamespace(
            games=args.games_per_tournament,
            stockfish_skill=0,
            seconds_per_move=args.seconds_per_move,
            max_plies=args.max_plies,
            stockfish=stockfish_path,
            own_book=True,
            learning=True,
            position_memory=enabled,
            output_dir=report_root / f"tournament-{index:02d}-memory-{'on' if enabled else 'off'}",
        )
        result = arena_run(cfg)
        record = {
            "tournament": index, "position_memory": "enabled" if enabled else "disabled",
            "wins": result["wins"], "draws": result["draws"], "losses": result["losses"],
            "completed_games": result["completed_games"], "errors": result["errors"],
            "incomplete": result["incomplete"], "score_percent": result["score_percent"],
            "games": result["games"],
        }
        rounds.append(record)
        print("TOURNAMENT_RESULT", json.dumps({k:v for k,v in record.items() if k!="games"}, sort_keys=True), flush=True)
        (report_root/"progress.json").write_text(json.dumps(rounds, indent=2)+"\n", encoding="utf-8")

    def aggregate(enabled):
        chosen = [r for r in rounds if (r["position_memory"] == "enabled") == enabled]
        totals = {k: sum(r[k] for r in chosen) for k in ("wins", "draws", "losses", "completed_games", "errors", "incomplete")}
        n = totals["completed_games"]
        totals["score_percent"] = round(100*(totals["wins"] + totals["draws"]*.5)/n,2) if n else None
        totals["tournaments"] = len(chosen)
        return totals

    report = {
        "schema": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "opponent": "Stockfish (system package)", "stockfish_skill": 0,
        "seconds_per_move": args.seconds_per_move, "games_per_tournament": 4,
        "tournaments": 4, "total_scheduled_games": 16, "max_plies": args.max_plies,
        "engine": "GM-1000 position-memory build",
        "memory_source_games": memory["source_games"],
        "memory_positions": memory["positions_count"],
        "memory_sha256": snapshot_sha,
        "memory_enabled": aggregate(True), "memory_disabled": aggregate(False),
        "rounds": rounds,
        "limitations": (
            "Only eight games per variant; no reliable Elo or strength conclusion. "
            "All games use the standard starting position, with alternated colors. "
            "Different Stockfish random choices can affect results; no paired-opening random seeds. "
            "This experiment does not train or modify model parameters."
        ),
    }
    assert sum(r["completed_games"] + r["errors"] + r["incomplete"] for r in rounds) == 16
    assert all(r["completed_games"] == 4 and r["errors"] == 0 and r["incomplete"] == 0 for r in rounds), "Incomplete/failed games: inspect run artifacts"
    if hashlib.sha256(memory_file.read_bytes()).hexdigest() != snapshot_sha:
        raise AssertionError("Study unexpectedly mutated the position memory")
    (report_root / "summary.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("FINAL_FOUR_TOURNAMENT_SUMMARY",json.dumps({k:v for k,v in report.items() if k != "rounds"},indent=2),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tournaments",type=int,default=4)
    p.add_argument("--games-per-tournament",type=int,default=4)
    p.add_argument("--skill",type=int,default=0)
    p.add_argument("--seconds-per-move",type=float,default=.2)
    p.add_argument("--max-plies",type=int,default=300)
    p.add_argument("--stockfish",default=None)
    p.add_argument("--output-dir",type=Path,default=ROOT/"reports"/"stockfish0-four")
    run(p.parse_args())


if __name__ == "__main__":
    main()
