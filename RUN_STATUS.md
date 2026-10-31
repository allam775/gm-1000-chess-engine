# GM-1000 actual GitHub execution status — 31 October 2026

Repository: https://github.com/allam775/gm-1000-chess-engine

## Verified source upload and CI
- All 20 original project files were uploaded to the public repository on branch `main`.
- Initial automated test suite: **SUCCESS** (GitHub Actions Engine checks).
- Test run: https://github.com/allam775/gm-1000-chess-engine/actions/runs/41188265745
- Additional Engine checks runs on later commits also passed.

## Historical study of 1,000 games
- Workflow: **SUCCESS**, including installation, PGN download/selection, 1,000-game integrity assertions, artifact upload and committing derived book files.
- Run: https://github.com/allam775/gm-1000-chess-engine/actions/runs/41188337360
- Source: PGN Mentor archives for ten historical players.
- Verified: 1,000 selected, unique game fingerprints, selection index and opening-book metadata.
- Saved to repository: `data/opening_book.json` and `data/selection_index.json`.
- PGN bundle is in the `selected-master-games` artifact (7-day retention).
- Artifact: https://github.com/allam775/gm-1000-chess-engine/actions/runs/41188337360/artifacts/13037129251

## First Stockfish baseline tournament
- Workflow: **SUCCESS**; all four matches completed and the results artifact was uploaded.
- Run: https://github.com/allam775/gm-1000-chess-engine/actions/runs/41188469678
- Opponent: distribution Stockfish, **Skill Level 0** (not a claimed Elo level).
- Time per move: **0.2 seconds**; colors alternated.
- Completed games: **4**.
- GM-1000 wins: **2**, draws: **0**, losses: **2**.
- Engine errors: **0**; incomplete games: **0**.
- Scored points: **50.0%**.
- All four games ended by checkmate.
- Complete PGN and `results.json` are provided in `tournament-results` artifact (30-day retention).
- Artifact: https://github.com/allam775/gm-1000-chess-engine/actions/runs/41188469678/artifacts/13037149448

## Scientific interpretation and limitations
This is a functional first baseline, **not** a validated Elo rating or evidence of Grandmaster-level strength. Four games against Stockfish at one artificially weakened setting are not statistically adequate for strength calibration. Later tests should increase match counts, keep the opponent version and time controls fixed, alternate colors, and report uncertainty.

The opening-book study builds a frequency-based opening book from complete source games; it does **not** train a neural network on their middle- or endgame positions. The engine itself performs independent Python alpha-beta search. Stockfish only acts as the separate tournament opponent.

## Repeat the experiments
Use the GitHub Actions tab and run `Engine checks`, `Study 1000 master games`, or `Engine arena` manually. The two initial experimental runs were additionally started by controlled, narrow push triggers under `.github/bootstrap-*.txt`. Normal pushes do not rerun those expensive jobs.

The GitHub-hosted public-repository standard runner was used; future use remains subject to GitHub's current billing policies and usage limits.
