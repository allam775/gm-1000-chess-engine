"""Measure whether the v0.4 near-position index actually covers old Skill5 games."""
from __future__ import annotations
import json
from pathlib import Path
import chess
import chess.pgn
from engine.search import Engine, book_key
from engine.position_patterns import build_index, pattern_candidates

ROOT=Path(__file__).resolve().parents[1]
sf=json.loads((ROOT/"data/stockfish19_position_memory.json").read_text(encoding="utf-8"))
gm=json.loads((ROOT/"data/position_memory.json").read_text(encoding="utf-8"))
index=build_index(sf["positions"])
assert sf["positions_count"]==43702 and gm["positions_count"]==32233

total=0
exact_sf=0
exact_gm=0
generalized=0
candidate_count=0
by_phase={"opening":[0,0],"middlegame":[0,0],"late":[0,0]}
for t in range(1,5):
    path=ROOT/f"data/skill5-original-pgn/tournament-{t:02d}.pgn"
    with path.open(encoding="utf-8") as f:
        for g in range(1,5):
            game=chess.pgn.read_game(f)
            assert game and not game.errors
            b=game.board()
            our_color=chess.WHITE if game.headers["White"]=="GM-1000" else chess.BLACK
            for ply,move in enumerate(game.mainline_moves(),1):
                if b.turn==our_color:
                    total+=1
                    key=book_key(b)
                    exact_sf+=int(key in sf["positions"])
                    exact_gm+=int(key in gm["positions"])
                    p=pattern_candidates(b,index)
                    generalized+=int(bool(p))
                    candidate_count+=len(p)
                    phase="opening" if ply<=20 else "middlegame" if ply<=60 else "late"
                    by_phase[phase][0]+=1
                    by_phase[phase][1]+=int(bool(p))
                b.push(move)
print("COVERAGE",json.dumps({"GM_moves":total,"SF19_exact":exact_sf,
      "GM_exact":exact_gm,"SF19_generalized_candidates_at_positions":generalized,
      "total_generated_candidate_moves":candidate_count,
      "by_phase":by_phase},indent=2),flush=True)
