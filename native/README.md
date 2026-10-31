# GM-1000 native search core (experimental)

This directory contains an **independently authored GM-1000 C++ search engine**.
Only the chess-rules and legal-move generator is an external dependency.

- Dependency: [Disservin/chess-library](https://github.com/Disservin/chess-library), single-header C++ chess-rule library, MIT.
- Pinned upstream commit: `3af102c53752472c208d48921ece705b1f0d1626`
- Original file: `include/chess.hpp`, blob SHA `54c484874a6aebcae544587b651208cfadcdd788`, license preserved in the header.
- The dependency handles board state and legal chess moves. **No Stockfish engine, evaluation, or search implementation is reused.**
- Builds with `g++ -std=c++17 -O3 -pthread -I native/third_party native/gm1000.cpp -o native/bin/gm1000-native` once the native source exists.
- The existing Python UCI remains the stable default. All strength claims require independently audited playing matches.

## Building and playing v0.6

Build on Linux or Windows (CMake 3.16+, C++17 compiler):

```sh
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release --parallel
```

Use the resulting `gm1000-native` binary (or `gm1000-native.exe` on Windows) as a **UCI engine** in a chess GUI. CI-built binaries are available from the [native cross-platform workflow](https://github.com/allam775/gm-1000-chess-engine/actions/workflows/native-portable.yml).

The experimental native engine currently **does not load the 560-grandmaster-game database, Stockfish19 overlay or v0.5 learned weights**. It tests an independently authored native alpha-beta + quiescence search and separate handcrafted static evaluation. The Python engine remains the repo's default. Do not infer an FIDE Elo or a 2500 rating from speed tests.

## Verified baseline (2026-10-31)

The [native versus Python matched-opening experiment](https://github.com/allam775/gm-1000-chess-engine/actions/runs/41201937084) at 0.2 seconds per move with both memories and opening books disabled produced 24 native wins, no draws and no losses (12 White, 12 Black). On the same 16 positions, median completed depth was 6 (native) versus 2 (Python), with reported median throughput 3,566,346 versus 7,507 nodes/second. **Evaluators differ**; this is evidence for the native *system*, not an isolated search-code improvement or calibrated Elo. Further Stockfish Skill5 A/B validation is required.
