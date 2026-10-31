# v0.11 audit-correction experiment

This branch is experimental. The engine is not promoted and no improvement in
win rate is claimed. All earlier sources, reports and branches are retained.

Two separate immutable engine commits follow the frozen v0.10 candidate:

1. `9fed02ad37f7f82096755056164005379821e742`: legal LVA exchange ordering,
   including king/pin legality, with SEE-based quiescence rejection removed.
2. `fa0925956188518134ed081de69cb3543753b03d`: the above plus draw-context TT
   guards. Score cutoffs require the same half-move clock and ordered reversible
   position history; a board-only match can still supply a move for ordering.
   Pawn moves/captures reset the context; null-search contexts are separated.

The LVA estimate is not an exact exchange oracle and is never a pruning proof.
The history guard is deliberately conservative and sacrifices transpositions
between different reversible move orders. This may reduce effective depth and
playing strength. Initial timings already show substantial throughput costs.
Correctness regressions passing do not imply improved game strength.

A local cold-search check on the first twenty frozen opening positions returned
median reported NPS of 4.22M (v0.8), 3.82M (v0.10), 2.54M (SEE repair), and
2.61M (both), with median completed depths 6, 6, 6, and 5.5. Raw records are in
`data/v11_audit_speed_local.json`. This measures a cost, not a playing improvement;
the CPU is shared, nodes include quiescence transitions, and timings are noisy.

## Frozen comparison

The 400-game workflow tests four arms: v0.8 baseline, v0.10 control, SEE repair
alone, and both repairs. Each receives 100 games against the exact official
Stockfish 17.1 AVX2 binary, Skill 5, one thread, 16 MiB hash, nominal 200 ms.
Fifty opening positions are frozen in `data/v11_audit_openings.json`, with both
colors per arm. The manifest excludes 320 distinct positions reconstructed
from known previous native tournament seed lists; it still uses the same
opening graph and makes no claim of distribution-wide independence.

The primary metric is actual wins / scheduled games. Draws never count as wins.
Errors and move-cap incompletes are explicit and invalidate complete aggregation.
Every played move records external elapsed time, available depth/nodes, and UCI
reported time. PGNs and telemetry are replayed and cross-checked before scoring.
The arbiter uses nominal move limits; it does not impose a strict 200 ms forfeit.

Results are archived without automatic promotion. The incremental comparisons
SEE-versus-v0.10 and both-versus-SEE help distinguish each step's playing effect.
Any confidence intervals are descriptive opening-clustered approximations;
100 games per arm cannot establish an underlying 90% win probability.

## Regressions

`tests/test_native_audit_corrections.py` compares small legal exchanges against
an independent python-chess capture-tree oracle. Its separate C++ probe checks
the clock-0/clock-99 TT counterexample, rejects an incompatible-history exact
entry, distinguishes transposed move orders, and verifies irreversible resets.
The ordinary repository test suite may skip native tests when no binary exists;
the dedicated tournament workflow explicitly builds the candidate before tests.
