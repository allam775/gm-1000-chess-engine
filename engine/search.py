"""GM-1000's independent, CPU-only evaluation and alpha-beta chess search.

python-chess generates and checks legal moves. It does not select our moves.
Scores are centipawns relative to the player to move.
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import chess
import chess.polyglot

PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 335,
                chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
MATE = 30000
INF = 32000


@dataclass
class SearchResult:
    move: chess.Move | None
    score: int = 0
    depth: int = 0
    nodes: int = 0
    pv: tuple[chess.Move, ...] = ()
    book: bool = False


@dataclass
class TTEntry:
    depth: int
    score: int
    flag: str
    move: chess.Move | None


class SearchTimeout(Exception):
    """The current iteration was interrupted. Earlier completed work survives."""


def book_key(board: chess.Board) -> str:
    """Position key independent of full-move and reversible-move counters."""
    return board.epd(en_passant="legal")


def evaluate(board: chess.Board) -> int:
    """Lightweight positional evaluation, never calls another chess engine."""
    score = 0
    pawn_files = {chess.WHITE: defaultdict(list), chess.BLACK: defaultdict(list)}
    for color in chess.COLORS:
        sign = 1 if color == chess.WHITE else -1
        bishops = len(board.pieces(chess.BISHOP, color))
        if bishops >= 2:
            score += sign * 25
        for square, piece in board.piece_map().items():
            if piece.color != color:
                continue
            kind = piece.piece_type
            score += sign * PIECE_VALUES[kind]
            file = chess.square_file(square)
            rank = chess.square_rank(square) if color == chess.WHITE else 7 - chess.square_rank(square)
            # Centralization (reduced for rooks, excluded for king in middlegame).
            center = (3.5 - abs(file - 3.5)) + (3.5 - abs(rank - 3.5))
            if kind in (chess.KNIGHT, chess.BISHOP):
                score += sign * round(center * (8 if kind == chess.KNIGHT else 5))
            elif kind == chess.QUEEN:
                score += sign * round(center * 2)
            elif kind == chess.PAWN:
                score += sign * (rank * 7 + round((3.5 - abs(file - 3.5)) * 3))
                pawn_files[color][file].append(square)
            elif kind == chess.ROOK:
                score += sign * (rank * 2)
        king = board.king(color)
        if king is not None:
            kf = chess.square_file(king)
            kr = chess.square_rank(king) if color == chess.WHITE else 7 - chess.square_rank(king)
            # When queens remain, favor secure/less exposed kings.
            if board.queens:
                score += sign * (12 if kr <= 1 else -8 * kr)
                guards = sum(1 for x in board.attackers(color, king) if board.piece_type_at(x) == chess.PAWN)
                score += sign * (guards * 8)
    for color in chess.COLORS:
        sign = 1 if color == chess.WHITE else -1
        for file, pawns in pawn_files[color].items():
            if len(pawns) > 1:
                score -= sign * 14 * (len(pawns) - 1)
            if not pawn_files[color].get(file - 1) and not pawn_files[color].get(file + 1):
                score -= sign * 12 * len(pawns)
            for square in pawns:
                our_rank = chess.square_rank(square)
                passed = True
                for ef in (file - 1, file, file + 1):
                    if not 0 <= ef <= 7:
                        continue
                    for enemy_square in pawn_files[not color].get(ef, []):
                        er = chess.square_rank(enemy_square)
                        if (er > our_rank) if color == chess.WHITE else (er < our_rank):
                            passed = False
                if passed:
                    advancement = our_rank if color == chess.WHITE else 7 - our_rank
                    score += sign * (10 + advancement * advancement * 2)
    return score if board.turn == chess.WHITE else -score


class Engine:
    def __init__(self, hash_mb: int = 32, book_path: str | Path = "data/opening_book.json"):
        self.hash_mb = max(1, hash_mb)
        self.table: dict[int, TTEntry] = {}
        self.killers: dict[int, list[chess.Move]] = {}
        self.nodes = 0
        self.deadline: float | None = None
        self.stop_event = threading.Event()
        self.book_path = Path(book_path)
        self.own_book = True
        self._book: dict | None = None

    def new_game(self) -> None:
        self.table.clear()
        self.killers.clear()

    def _load_book(self) -> dict:
        if self._book is None:
            try:
                raw = json.loads(self.book_path.read_text(encoding="utf-8"))
                self._book = raw.get("positions", {})
            except (OSError, ValueError):
                self._book = {}
        return self._book

    def book_move(self, board: chess.Board) -> chess.Move | None:
        if not self.own_book:
            return None
        choices = self._load_book().get(book_key(board), {})
        for uci, _ in sorted(choices.items(), key=lambda item: (-item[1], item[0])):
            try:
                move = chess.Move.from_uci(uci)
                if move in board.legal_moves:
                    return move
            except ValueError:
                continue
        return None

    def _check_time(self) -> None:
        if self.stop_event.is_set() or (self.deadline is not None and time.monotonic() >= self.deadline):
            raise SearchTimeout()

    def _drawn(self, board: chess.Board) -> bool:
        return (board.is_stalemate() or board.is_insufficient_material()
                or board.is_fivefold_repetition() or board.is_seventyfive_moves()
                or (board.halfmove_clock >= 8 and board.is_repetition(3))
                or board.halfmove_clock >= 100)

    def _ordered(self, board: chess.Board, moves: list[chess.Move], ply: int,
                 preferred: chess.Move | None = None) -> list[chess.Move]:
        killers = self.killers.get(ply, [])
        def priority(move: chess.Move) -> int:
            if preferred == move:
                return 100000
            if board.is_capture(move):
                attacker = board.piece_type_at(move.from_square) or chess.PAWN
                victim = board.piece_type_at(move.to_square) or chess.PAWN
                return 10000 + 20 * PIECE_VALUES[victim] - PIECE_VALUES[attacker]
            if move.promotion:
                return 9500 + PIECE_VALUES[move.promotion]
            if move in killers:
                return 7000 - 100 * killers.index(move)
            return 0
        return sorted(moves, key=priority, reverse=True)

    def _quiescence(self, board: chess.Board, alpha: int, beta: int, ply: int,
                    qdepth: int = 0) -> int:
        self.nodes += 1
        if self.nodes % 256 == 0:
            self._check_time()
        if board.is_checkmate():
            return -MATE + ply
        if self._drawn(board):
            return 0
        in_check = board.is_check()
        stand_pat = evaluate(board)
        if not in_check:
            if stand_pat >= beta:
                return beta
            alpha = max(alpha, stand_pat)
        if qdepth >= 8:
            # In check, cannot treat an attacked king as a quiet position.
            if not in_check:
                return alpha
            if qdepth >= 12:
                return stand_pat
        if in_check:
            moves = list(board.legal_moves)
        else:
            moves = [m for m in board.legal_moves if board.is_capture(m) or m.promotion]
        for move in self._ordered(board, moves, ply):
            board.push(move)
            try:
                score = -self._quiescence(board, -beta, -alpha, ply + 1, qdepth + 1)
            finally:
                board.pop()
            if score >= beta:
                return beta
            alpha = max(alpha, score)
        return alpha

    def _negamax(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if self.nodes % 256 == 0:
            self._check_time()
        if board.is_checkmate():
            return -MATE + ply
        if self._drawn(board):
            return 0
        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply)
        key = chess.polyglot.zobrist_hash(board)
        entry = self.table.get(key)
        original_alpha = alpha
        if entry and entry.depth >= depth:
            tt_score = entry.score
            if abs(tt_score) > MATE - 512:
                # Mate-distance scores depend on search ply; avoid unsafe reuse.
                tt_score = None
            if tt_score is not None:
                if entry.flag == 'exact':
                    return tt_score
                if entry.flag == 'lower':
                    alpha = max(alpha, tt_score)
                elif entry.flag == 'upper':
                    beta = min(beta, tt_score)
                if alpha >= beta:
                    return tt_score
        moves = self._ordered(board, list(board.legal_moves), ply, entry.move if entry else None)
        best = -INF
        best_move = None
        for move in moves:
            board.push(move)
            try:
                score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
            finally:
                board.pop()
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                if not board.is_capture(move):
                    killers = self.killers.setdefault(ply, [])
                    if move not in killers:
                        killers.insert(0, move)
                        del killers[2:]
                break
        if len(self.table) >= self.hash_mb * 350:
            self.table.clear()  # Simple bounded cache: avoid unbounded RAM growth.
        flag = 'upper' if best <= original_alpha else 'lower' if best >= beta else 'exact'
        self.table[key] = TTEntry(depth, best, flag, best_move)
        return best

    def _pv(self, board: chess.Board, depth: int) -> tuple[chess.Move, ...]:
        path = []
        copy = board.copy(stack=False)
        seen: set[int] = set()
        for _ in range(depth):
            key = chess.polyglot.zobrist_hash(copy)
            if key in seen:
                break
            seen.add(key)
            entry = self.table.get(key)
            if not entry or not entry.move or entry.move not in copy.legal_moves:
                break
            path.append(entry.move)
            copy.push(entry.move)
        return tuple(path)

    def search(self, board: chess.Board, time_limit: float | None = 0.2, depth: int = 64,
               info: Callable[[SearchResult], None] | None = None,
               allow_book: bool = True) -> SearchResult:
        self.nodes = 0
        self.deadline = time.monotonic() + max(0.01, time_limit) if time_limit is not None else None
        if board.is_game_over(claim_draw=True):
            return SearchResult(None)
        if allow_book:
            bm = self.book_move(board)
            if bm:
                return SearchResult(bm, book=True, pv=(bm,))
        legal = list(board.legal_moves)
        if not legal:
            return SearchResult(None)
        result = SearchResult(legal[0])
        for current_depth in range(1, min(depth, 64) + 1):
            if self.stop_event.is_set():
                break
            try:
                self._check_time()
                original_alpha, beta = -INF, INF
                best_score = -INF
                best_move = None
                key = chess.polyglot.zobrist_hash(board)
                preferred = self.table.get(key)
                for move in self._ordered(board, legal, 0, preferred.move if preferred else result.move):
                    board.push(move)
                    try:
                        score = -self._negamax(board, current_depth - 1, -beta, -original_alpha, 1)
                    finally:
                        board.pop()
                    if score > best_score:
                        best_score, best_move = score, move
                    original_alpha = max(original_alpha, score)
                if best_move is None:
                    break
                self.table[key] = TTEntry(current_depth, best_score, 'exact', best_move)
                pv = self._pv(board, current_depth)
                result = SearchResult(best_move, best_score, current_depth, self.nodes, pv or (best_move,))
                if info:
                    info(result)
                if abs(best_score) >= MATE - 100:
                    break
            except SearchTimeout:
                break
        result.nodes = self.nodes
        return result
