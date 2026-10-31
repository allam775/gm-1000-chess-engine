"""Conservative near-position hints from the archived Stockfish 19 evidence.

No pseudo-learning and no move substitution: merely rank legal *candidate*
moves if pawn structure, material inventory, castling rights, and side match.
A small number of nonpawn square differences is required. Actual alpha-beta
search remains responsible for move choice.
"""
from __future__ import annotations
from collections import defaultdict
import chess


def expanded(epd: str):
    parts = epd.split()
    if len(parts) < 4:
        raise ValueError("Bad EPD key")
    squares = []
    for rank in parts[0].split("/"):
        if len(squares) > 64:
            raise ValueError("Bad EPD ranks")
        for c in rank:
            if c.isdigit():
                squares.extend("." * int(c))
            else:
                squares.append(c)
    if len(squares) != 64:
        raise ValueError("Bad EPD board")
    pawns = tuple((i, c) for i, c in enumerate(squares) if c in "pP")
    material = "".join(sorted(c for c in squares if c.isalpha() and c not in "pP"))
    return ((parts[1], parts[2], pawns, material), tuple(squares))


def build_index(positions: dict) -> dict:
    """Construct once per loaded memory snapshot; only keep vetted preferences."""
    index = defaultdict(list)
    for epd, data in positions.items():
        if not isinstance(data, dict) or not isinstance(data.get("preferred_move"), str):
            continue
        try:
            signature, squares = expanded(epd)
            move = chess.Move.from_uci(data["preferred_move"])
        except (ValueError, TypeError):
            continue
        index[signature].append((squares, move))
    return dict(index)


def pattern_candidates(board: chess.Board, index: dict,
                       *, max_difference: int = 4, max_moves: int = 3):
    """Legality-checked short candidate list, never a forced playing decision."""
    from .search import book_key
    signature, squares = expanded(book_key(board))
    matches = index.get(signature, ())
    counts = {}
    for stored, move in matches:
        differences = sum(x != y for x, y in zip(stored, squares))
        if 0 < differences <= max_difference and move in board.legal_moves:
            score = max_difference + 1 - differences
            counts[move] = counts.get(move, 0) + score
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].uci()))[:max_moves]
