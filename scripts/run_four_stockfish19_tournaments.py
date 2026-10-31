"""Four fresh mini-tournaments isolating the Stockfish-19 position-memory upgrade.

Two four-game tournaments use GM history + the new Stockfish-19 overlay.
Two four-game tournaments use the same GM history, but overlay disabled.
Both face Stockfish Skill Level 0 with alternating colors and identical
timing. Match results are descriptive only, not a reliable Elo estimate.
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
    if args.tournaments != 4 or args.games_per_tournament != 4 or args.skill != 0:
        raise ValueError("Exactly four 4-game tournaments vs Stockfish Skill 0 required")
    if args.seconds_per_move < .02:
        raise ValueError("Thinking time must be >=0.02s")

    gm_path = ROOT / "data/position_memory.json"
    sf_path = ROOT / "data/stockfish19_position_memory.json"
    sf_report_path = ROOT / "data/stockfish19_position_memory_report.json"
    gm = json.loads(gm_path.read_text(encoding="utf-8"))
    sf = json.loads(sf_path.read_text(encoding="utf-8"))
    sf_report = json.loads(sf_report_path.read_text(encoding="utf-8"))
    if gm.get("source_games") != 560 or gm.get("positions_count") != 32233:
        raise AssertionError("Wrong grandmaster memory snapshot")
    if sf.get("schema") != 1 or sf.get("games") != 400 or sf.get("positions_count") != 43702:
        raise AssertionError("400-game Stockfish 19 memory overlay unavailable")
    if sf_report.get("engine_version") != "Stockfish 19" or sf_report.get("stockfish_skill") != 20:
        raise AssertionError("Study provenance mismatch")
    original_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (gm_path, sf_path)}
    stockfish_bin = args.stockfish or os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    if not stockfish_bin and Path("/usr/games/stockfish").exists():
        stockfish_bin = "/usr/games/stockfish"
    if not stockfish_bin:
        raise FileNotFoundError("Stockfish opponent unavailable")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rounds = []
    # A B B A balances variant order. Each mini-tournament alternates
    # GM colors W/B/W/B; both variants retain the original grandmaster memory.
    for index, overlay_on in enumerate((True, False, False, True), 1):
        folder = args.output_dir / f"tournament-{index:02d}-sf19-{'on' if overlay_on else 'off'}"
        cfg = SimpleNamespace(games=4, stockfish_skill=0, stockfish=stockfish_bin,
                              seconds_per_move=args.seconds_per_move,
                              max_plies=args.max_plies, output_dir=folder,
                              own_book=True, learning=True,
                              position_memory=True, stockfish_memory=overlay_on)
        result = arena_run(cfg)
        record = {"tournament": index,
                  "stockfish19_overlay": "enabled" if overlay_on else "disabled",
                  "grandmaster_memory": "enabled",
                  "wins": result["wins"], "draws": result["draws"],
                  "losses": result["losses"], "completed_games": result["completed_games"],
                  "errors": result["errors"], "incomplete": result["incomplete"],
                  "score_percent": result["score_percent"], "games": result["games"]}
        rounds.append(record)
        (args.output_dir / "progress.json").write_text(json.dumps(rounds, indent=2)+"\n",
                                                       encoding="utf-8")
        print("TOURNAMENT_RESULT",json.dumps({k:v for k,v in record.items() if k!="games"}),
              flush=True)

    def combined(flag):
        selected = [r for r in rounds if (r["stockfish19_overlay"] == "enabled") == flag]
        fields = ("wins", "draws", "losses", "completed_games", "errors", "incomplete")
        stats = {k: sum(x[k] for x in selected) for k in fields}
        n = stats["completed_games"]
        stats["score_percent"] = round(100*(stats["wins"]+.5*stats["draws"])/n,2) if n else None
        stats["tournaments"] = len(selected)
        return stats

    result = {
        "schema": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "study": "400 games Stockfish 19 Skill Level 20 self-play (position overlay)",
        "opponent": "Stockfish installed Ubuntu package (Skill Level 0)",
        "stockfish_skill": 0, "games_per_tournament": 4, "tournaments": 4,
        "games_scheduled": 16, "seconds_per_move": args.seconds_per_move,
        "max_plies": args.max_plies,
        "grandmaster_memory": "enabled in both groups",
        "grandmaster_memory_positions": gm["positions_count"],
        "stockfish19_memory_positions": sf["positions_count"],
        "stockfish19_study_games": sf["games"],
        "stockfish19_overlay_enabled": combined(True),
        "stockfish19_overlay_disabled": combined(False),
        "rounds": rounds,
        "limitation": "8 games per variant from standard startpos, Stockfish skill-0 may vary; not a statistically controlled Elo estimate or paired-opening benchmark. Model and memory files are not changed."
    }
    if sum(r["completed_games"]+r["incomplete"]+r["errors"] for r in rounds) != 16:
        raise AssertionError("Incomplete tournament accounting")
    for path, sha in original_hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha:
            raise AssertionError("Arena mutated long-term learned memory")
    (args.output_dir / "summary.json").write_text(json.dumps(result,indent=2)+"\n",
                                                  encoding="utf-8")
    print("FINAL_TOURNAMENT_RESULT",json.dumps({k:v for k,v in result.items() if k!="rounds"},
                                               indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tournaments",type=int,default=4)
    parser.add_argument("--games-per-tournament",type=int,default=4)
    parser.add_argument("--skill",type=int,default=0)
    parser.add_argument("--seconds-per-move",type=float,default=.2)
    parser.add_argument("--max-plies",type=int,default=300)
    parser.add_argument("--stockfish",default=None)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"reports"/"stockfish19-memory-four")
    run(parser.parse_args())


if __name__=="__main__":
    main()
