# GM-1000 native search core (experimental)

This directory contains an **independently authored GM-1000 C++ search engine**.
Only the chess-rules and legal-move generator is an external dependency.

- Dependency: [Disservin/chess-library](https://github.com/Disservin/chess-library), single-header C++ chess-rule library, MIT.
- Pinned upstream commit: `3af102c53752472c208d48921ece705b1f0d1626`
- Original file: `include/chess.hpp`, blob SHA `54c484874a6aebcae544587b651208cfadcdd788`, license preserved in the header.
- The dependency handles board state and legal chess moves. **No Stockfish engine, evaluation, or search implementation is reused.**
- Builds with `g++ -std=c++17 -O3 -pthread -I native/third_party native/gm1000.cpp -o native/bin/gm1000-native` once the native source exists.
- The existing Python UCI remains the stable default. All strength claims require independently audited playing matches.
