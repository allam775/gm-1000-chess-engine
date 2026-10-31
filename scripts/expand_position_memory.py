"""Expand GM-1000 exact-position memory by 400 distinct *new* titled-GM games.

Preserves the original 160-game memory, excludes all 40 held-out validation
games and the 1,000 original opening-book study games, and records each new
source-game SHA-256 so future expansions cannot relearn the same games.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.position_memory import build_position_memory
from scripts.build_book import get_source, parse_candidates, select_round_robin
from scripts.study_gm_games import GRANDMASTERS


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(fingerprints):
    return hashlib.sha256("\n".join(sorted(fingerprints)).encode("ascii")).hexdigest()


def merge_positions(old: dict, additions: dict) -> dict:
    """Accumulate count and player frequency without losing prior observations."""
    merged = {position: {
        move: {"count": stats["count"], "players": dict(stats["players"])}
        for move, stats in choices.items()
    } for position, choices in old.items()}
    for position, choices in additions.items():
        target = merged.setdefault(position, {})
        for move, stats in choices.items():
            existing = target.setdefault(move, {"count": 0, "players": {}})
            existing["count"] += int(stats["count"])
            for player, count in stats["players"].items():
                existing["players"][player] = existing["players"].get(player, 0) + int(count)
    return merged


def run(args):
    if args.additional != 400:
        raise ValueError("This audited workflow requires exactly 400 additional games")
    previous = load_json(args.memory)
    previous_report = load_json(args.report)
    study_index = load_json(args.study_index)
    opening_index = load_json(args.opening_index)
    if previous.get("schema") != 1 or previous["source_games"] < 160:
        raise ValueError("Missing original committed 160-game memory")
    if previous_report["source_games"] != previous["source_games"]:
        raise AssertionError("Existing memory/report game count mismatch")
    if previous.get("holdout_games_excluded") != 40:
        raise AssertionError("Original forty holdout games must remain excluded")
    assert previous["max_plies"] == args.max_plies, "Cannot mix differently truncated histories"
    original_study_hashes = {x["sha256"] for x in study_index}
    if len(original_study_hashes) != 200:
        raise AssertionError("Original game-index deduplication mismatch")
    held_out = {x["sha256"] for x in study_index if x["split"] == "validation"}
    original_training = {x["sha256"] for x in study_index if x["split"] == "training"}
    if len(held_out) != 40 or len(original_training) != 160:
        raise AssertionError("Incorrect original train/validation partition")
    if digest(held_out) != previous["validation_games_sha256"]:
        raise AssertionError("Validation game digest changed")
    if digest(original_training) != previous["training_games_sha256"]:
        raise AssertionError("Original training game digest changed")
    old_book_hashes = {x["fingerprint_sha256"] for x in opening_index["items"]}
    if len(old_book_hashes) != 1000:
        raise AssertionError("Expected original 1000-game opening-book index")
    earlier = load_json(args.expansion_index) if args.expansion_index.exists() else {"schema": 1, "games": []}
    if earlier.get("schema") != 1:
        raise AssertionError("Unknown memory expansion registry schema")
    earlier_hashes = {x["sha256"] for x in earlier["games"]}
    if len(earlier_hashes) != len(earlier["games"]):
        raise AssertionError("Duplicate earlier expansion game")
    if previous["source_games"] != 160 + len(earlier_hashes):
        raise AssertionError("Memory source count differs from expansion registry")
    excluded = original_study_hashes | old_book_hashes | earlier_hashes

    candidates_by = {}
    for player in GRANDMASTERS:
        pgn = get_source(player, args.source_dir, args.cache_dir)
        pool, scanned = parse_candidates(pgn, player, max(args.pool_per_player, 350))
        fresh = [game for game in pool if game.fingerprint not in excluded]
        candidates_by[player] = fresh
        print("CANDIDATES", player, "scanned", scanned, "eligible fresh", len(fresh), flush=True)

    selected = select_round_robin(candidates_by, args.additional)
    new_hashes = {g.fingerprint for g in selected}
    if len(selected) != args.additional or len(new_hashes) != args.additional:
        raise RuntimeError("Could not find exactly 400 unique additional grandmaster games")
    if new_hashes & excluded or new_hashes & held_out:
        raise AssertionError("Duplicate or held-out game leaked into new training")
    per_player = dict(sorted(Counter(g.source for g in selected).items()))
    # Ensure all eight GMs contribute, not only one player's games.
    if len(per_player) != len(GRANDMASTERS) or min(per_player.values()) < 20:
        raise AssertionError("Additional games are insufficiently distributed among grandmasters")

    new = build_position_memory(selected, max_plies=args.max_plies)
    old_positions = previous["positions"]
    merged = merge_positions(old_positions, new["positions"])
    for epd, choices in old_positions.items():
        for uci, data in choices.items():
            retained = merged[epd][uci]
            if retained["count"] < data["count"]:
                raise AssertionError("Previous memorized move count decreased")
            for player, count in data["players"].items():
                if retained["players"].get(player, 0) < count:
                    raise AssertionError("Previous grandmaster observation was lost")

    result = dict(previous)
    result["source"] = "Named titled grandmaster positions: original 160 training games plus verified additional unique source games"
    result["source_games"] = previous["source_games"] + args.additional
    result["positions"] = merged
    result["positions_count"] = len(merged)
    result["move_pairs_count"] = sum(len(choices) for choices in merged.values())
    result["observations"] = previous["observations"] + new["observations"]
    result["holdout_games_excluded"] = 40
    result["additional_source_games"] = len(earlier_hashes) + args.additional
    result["additional_game_ids_sha256"] = digest(earlier_hashes | new_hashes)
    result["original_opening_book_games_excluded"] = len(old_book_hashes)
    result["extension_utc"] = datetime.now(timezone.utc).isoformat()

    additions_index = [{
        "sha256": g.fingerprint, "player": g.source,
        "event": g.headers.get("Event", ""),
        "date": g.headers.get("Date", ""),
        "plies": len(g.moves)
    } for g in selected]
    registry = {"schema": 1, "original_training_games": 160,
                "original_holdout_games_excluded": 40,
                "original_opening_book_games_excluded": len(old_book_hashes),
                "games": earlier["games"] + additions_index}
    report = dict(previous_report)
    report.update({
        "source": result["source"],
        "source_games": result["source_games"],
        "positions_count": result["positions_count"],
        "move_pairs_count": result["move_pairs_count"],
        "observations": result["observations"],
        "holdout_games_excluded": 40,
        "additional_source_games": result["additional_source_games"],
        "new_games_this_run": args.additional,
        "new_game_ids_sha256": digest(new_hashes),
        "new_game_distribution": per_player,
        "new_positions_in_this_batch": new["positions_count"],
        "new_move_observations_in_this_batch": new["observations"],
        "positions_gained": result["positions_count"] - previous["positions_count"],
        "move_pairs_gained": result["move_pairs_count"] - previous["move_pairs_count"],
        "observations_gained": result["observations"] - previous["observations"],
        "previous_source_games": previous["source_games"],
        "previous_positions_count": previous["positions_count"],
        "original_opening_book_games_excluded": len(old_book_hashes),
        "selection": "400 entirely new titled-GM games; exclude prior 200 (including 40 holdout), original 1000-book games and prior expansions",
        "limitation": "Exact-position recall; no claim of increased playing strength without matched chess tournaments.",
        "extension_utc": result["extension_utc"],
    })
    args.memory.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.expansion_index.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    print("EXPANSION_REPORT", json.dumps({key: val for key, val in report.items() if key not in
        ("players",)}, sort_keys=True, indent=2), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--additional", type=int, default=400)
    p.add_argument("--max-plies", type=int, default=180)
    p.add_argument("--pool-per-player", type=int, default=500)
    p.add_argument("--cache-dir", type=Path, default=ROOT / "data/cache")
    p.add_argument("--source-dir", type=Path, default=None)
    p.add_argument("--memory", type=Path, default=ROOT / "data/position_memory.json")
    p.add_argument("--report", type=Path, default=ROOT / "data/position_memory_report.json")
    p.add_argument("--study-index", type=Path, default=ROOT / "data/gm_study_game_index_v02.json")
    p.add_argument("--opening-index", type=Path, default=ROOT / "data/selection_index.json")
    p.add_argument("--expansion-index", type=Path, default=ROOT / "data/position_memory_expansion_index.json")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
