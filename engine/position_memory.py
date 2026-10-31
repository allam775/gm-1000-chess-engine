"""Exact chess-position memory from audited PGN games.

Positions are EPD (piece placement, side, castling and legal en-passant).
Records name the move a selected grandmaster played, not a proven best move.
Only the named grandmaster's moves are included; validation games stay excluded.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

import chess

from .search import book_key


def build_position_memory(games, *, max_plies: int = 180) -> dict:
    """Build a deterministic position -> observed grandmaster moves database.

    `games` is a list of distinct scripts.build_book.Candidate records. A game
    contributes only the moves made by the particular GM named by its source.
    """
    if max_plies < 2:
        raise ValueError('max_plies must be >= 2')
    from scripts.study_gm_games import expert_color

    seen = set()
    positions = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'players': Counter()}))
    observations = 0
    for game in games:
        if game.fingerprint in seen:
            raise ValueError('Duplicate source game fingerprint in memory input')
        seen.add(game.fingerprint)
        gm_color = expert_color(game)
        board = chess.Board()
        for ply, uci in enumerate(game.moves):
            if ply >= max_plies:
                break
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f'Illegal source move at ply {ply}: {uci}')
            if board.turn == gm_color:
                entry = positions[book_key(board)][uci]
                entry['count'] += 1
                entry['players'][game.source] += 1
                observations += 1
            board.push(move)
    entries = {}
    for position, moves in sorted(positions.items()):
        entries[position] = {
            uci: {'count': stats['count'], 'players': dict(sorted(stats['players'].items()))}
            for uci, stats in sorted(moves.items(), key=lambda pair: (-pair[1]['count'], pair[0]))
        }
    return {
        'schema': 1,
        'source': 'titled GM moves from game-disjoint training partition of GM-1000 v0.2 200-game study',
        'source_games': len(seen),
        'max_plies': max_plies,
        'positions_count': len(entries),
        'move_pairs_count': sum(len(m) for m in entries.values()),
        'observations': observations,
        'positions': entries,
    }


def legal_memory_moves(board: chess.Board, memory: dict) -> list[tuple[chess.Move, int]]:
    """Return only legal memorized moves in descending observation frequency."""
    if memory.get('schema') != 1:
        return []
    rows = memory.get('positions', {}).get(book_key(board), {})
    moves = []
    for uci, data in rows.items():
        try:
            move = chess.Move.from_uci(uci)
            count = int(data['count'])
            if count > 0 and move in board.legal_moves:
                moves.append((move, count))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(moves, key=lambda x: (-x[1], x[0].uci()))


def choose_safe_recalled_move(
    memory_moves: list[tuple[chess.Move, int]],
    move_scores: dict[chess.Move, int],
    best_score: int,
    *,
    margin_cp: int = 20,
    mate_score: int = 30000,
) -> chess.Move | None:
    """Prefer a remembered move only when search evaluated it close to best.

    Do not overrule detected mating wins, or select known losing mate lines.
    The search's current depth still determines tactical safety; this is not
    a guarantee that a remembered move is objectively sound.
    """
    if abs(best_score) >= mate_score - 200:
        return None
    candidates = [
        (score, count, move.uci(), move)
        for move, count in memory_moves
        if (score := move_scores.get(move)) is not None
        and score >= best_score - margin_cp
        and score > -mate_score + 200
    ]
    if not candidates:
        return None
    # Highest count wins among tactically close moves; prefer higher score on ties.
    _, _, _, move = max(candidates, key=lambda x: (x[1], x[0], x[2]))
    return move
