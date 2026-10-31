"""Four 4-game GM-1000 tournaments vs Stockfish Skill Level 5.

All games have both 560-game grandmaster history and the verified Stockfish 19
400-game position overlay enabled. This experiment measures playing outcomes;
it does not train or change either memory database.
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


def read_memory_snapshots() -> tuple[dict, dict, dict[str, str]]:
    gm_path = ROOT / "data" / "position_memory.json"
    sf_path = ROOT / "data" / "stockfish19_position_memory.json"
    gm = json.loads(gm_path.read_text(encoding="utf-8"))
    sf = json.loads(sf_path.read_text(encoding="utf-8"))
    if gm.get("schema") != 1 or gm.get("source_games") != 560 or gm.get("positions_count") != 32233:
        raise AssertionError("Expected verified 560-grandmaster-game memory")
    if sf.get("schema") != 1 or sf.get("games") != 400 or sf.get("positions_count") != 43702:
        raise AssertionError("Expected verified 400-game Stockfish19 overlay")
    if sf.get("stockfish_skill") != 20 or not sf.get("engine_version", "").startswith("Stockfish 19"):
        raise AssertionError("Stockfish overlay provenance mismatch")
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (gm_path, sf_path)}
    return gm, sf, hashes


def tally(rounds: list[dict]) -> dict:
    keys = ("wins", "draws", "losses", "completed_games", "errors", "incomplete")
    data = {key: sum(record[key] for record in rounds) for key in keys}
    total = data["completed_games"]
    data["score_percent"] = round(100 * (data["wins"] + .5 * data["draws"]) / total, 2) if total else None
    data["tournaments_completed"] = len(rounds)
    return data


def run(args) -> dict:
    if (args.tournaments, args.games_per_tournament, args.skill) != (4, 4, 5):
        raise ValueError("This study requires four tournaments, four games each, Stockfish Skill Level 5")
    if args.seconds_per_move < 0.02 or args.max_plies < 1:
        raise ValueError("Invalid time limit or maximum plies")
    gm, sf, checksums = read_memory_snapshots()
    binary = args.stockfish or os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    if not binary and Path("/usr/games/stockfish").is_file():
        binary = "/usr/games/stockfish"
    if not binary:
        raise FileNotFoundError("Stockfish opponent executable not found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rounds = []
    for number in range(1, 5):
        cfg = SimpleNamespace(games=4, stockfish_skill=5,
                              seconds_per_move=args.seconds_per_move,
                              max_plies=args.max_plies, stockfish=binary,
                              output_dir=args.output_dir / f"tournament-{number:02d}",
                              own_book=True, learning=True,
                              position_memory=True, stockfish_memory=True)
        arena = arena_run(cfg)
        assert arena["config"]["stockfish_skill"] == 5
        assert arena["config"]["position_memory"] is True
        assert arena["config"]["stockfish_memory"] is True
        row = {
            "tournament": number,
            "stockfish_skill": 5,
            "grandmaster_memory": "enabled",
            "stockfish19_memory": "enabled",
            "wins": arena["wins"], "draws": arena["draws"],
            "losses": arena["losses"], "completed_games": arena["completed_games"],
            "errors": arena["errors"], "incomplete": arena["incomplete"],
            "score_percent": arena["score_percent"], "games": arena["games"]
        }
        rounds.append(row)
        (args.output_dir / "progress.json").write_text(json.dumps(rounds, indent=2) + "\n", encoding="utf-8")
        print("TOURNAMENT_RESULT", json.dumps({k: v for k, v in row.items() if k != "games"}), flush=True)

    overall = tally(rounds)
    if overall["completed_games"] + overall["incomplete"] + overall["errors"] != 16:
        raise AssertionError("Tournament accounting doesn't match the 16 scheduled games")
    for path, old_digest in checksums.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != old_digest:
            raise AssertionError("A memory database was unexpectedly modified during tournament")

    report = {
        "schema": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "GM-1000 (both grandmaster and Stockfish 19 memories enabled)",
        "opponent": "Stockfish Ubuntu package",
        "opponent_skill_level": 5,
        "stockfish_skill_is_not_elo": True,
        "tournaments": 4,
        "games_per_tournament": 4,
        "scheduled_games": 16,
        "seconds_per_move": args.seconds_per_move,
        "max_plies": args.max_plies,
        "original_opening_book": True,
        "grandmaster_memory_enabled": True,
        "grandmaster_memory_games": gm["source_games"],
        "grandmaster_memory_positions": gm["positions_count"],
        "stockfish19_memory_enabled": True,
        "stockfish19_study_games": sf["games"],
        "stockfish19_memory_positions": sf["positions_count"],
        "memory_sha256": checksums,
        "totals": overall,
        "rounds": rounds,
        "limitations": "Only 16 games; results from the standard starting position and alternating colors. No Elo estimate or evidence of performance against other skill levels; training data and engine weights unchanged."
    }
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("FINAL_SKILL5_SUMMARY", json.dumps({k: v for k, v in report.items() if k != "rounds"}, indent=2), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tournaments", type=int, default=4)
    parser.add_argument("--games-per-tournament", type=int, default=4)
    parser.add_argument("--skill", type=int, default=5)
    parser.add_argument("--seconds-per-move", type=float, default=.2)
    parser.add_argument("--max-plies", type=int, default=300)
    parser.add_argument("--stockfish", default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "stockfish-skill5-four")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
