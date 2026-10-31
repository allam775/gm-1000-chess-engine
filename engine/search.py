"""GM-1000's independent, CPU-only evaluation and alpha-beta chess search.

python-chess generates and checks legal moves. It does not select our moves.
Scores are centipawns relative to the player to move.
"""
from __future__ import annotations

import json
import math
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


# Tunable non-material feature multipliers; material is fixed for stability.
LEARNABLE_FEATURES = ('bishop_pair', 'minor_center', 'queen_center',
                      'pawn_progress', 'pawn_center', 'rook_activity',
                      'king_safety', 'pawn_structure', 'passed_pawns',
                      'development', 'hanging_pieces')


def evaluate_components(board: chess.Board) -> dict[str, int]:
    """Break down white-minus-black evaluation into reproducible features."""
    features = {'material': 0, **{key: 0 for key in LEARNABLE_FEATURES}}
    pawn_files = {chess.WHITE: defaultdict(list), chess.BLACK: defaultdict(list)}
    pieces = board.piece_map()
    for color in chess.COLORS:
        sign = 1 if color == chess.WHITE else -1
        if len(board.pieces(chess.BISHOP, color)) >= 2:
            features['bishop_pair'] += sign * 25
        for square, piece in pieces.items():
            if piece.color != color:
                continue
            kind = piece.piece_type
            features['material'] += sign * PIECE_VALUES[kind]
            file = chess.square_file(square)
            rank = chess.square_rank(square) if color == chess.WHITE else 7 - chess.square_rank(square)
            center = (3.5 - abs(file - 3.5)) + (3.5 - abs(rank - 3.5))
            if kind in (chess.KNIGHT, chess.BISHOP):
                features['minor_center'] += sign * round(center * (8 if kind == chess.KNIGHT else 5))
            elif kind == chess.QUEEN:
                features['queen_center'] += sign * round(center * 2)
            elif kind == chess.PAWN:
                features['pawn_progress'] += sign * rank * 7
                features['pawn_center'] += sign * round((3.5 - abs(file - 3.5)) * 3)
                pawn_files[color][file].append(square)
            elif kind == chess.ROOK:
                features['rook_activity'] += sign * rank * 2
        king = board.king(color)
        if king is not None and board.queens:
            kr = chess.square_rank(king) if color == chess.WHITE else 7 - chess.square_rank(king)
            features['king_safety'] += sign * (12 if kr <= 1 else -8 * kr)
            guards = sum(1 for x in board.attackers(color, king) if board.piece_type_at(x) == chess.PAWN)
            features['king_safety'] += sign * guards * 8
    for color in chess.COLORS:
        sign = 1 if color == chess.WHITE else -1
        for file, pawns in pawn_files[color].items():
            if len(pawns) > 1:
                features['pawn_structure'] -= sign * 14 * (len(pawns) - 1)
            if not pawn_files[color].get(file - 1) and not pawn_files[color].get(file + 1):
                features['pawn_structure'] -= sign * 12 * len(pawns)
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
                    features['passed_pawns'] += sign * (10 + advancement * advancement * 2)
    # Opening development and undefended hanging minor/major pieces.
    # These modest bonuses complement (rather than replace) tactical search.
    for color in chess.COLORS:
        sign = 1 if color == chess.WHITE else -1
        back = 0 if color == chess.WHITE else 7
        for file in (1, 6):
            sq = chess.square(file, back)
            if board.piece_type_at(sq) == chess.KNIGHT and board.color_at(sq) == color:
                features['development'] -= sign * 9
        for file in (2, 5):
            sq = chess.square(file, back)
            if board.piece_type_at(sq) == chess.BISHOP and board.color_at(sq) == color:
                features['development'] -= sign * 7
        king = board.king(color)
        if king is not None and board.queens:
            kr, kf = chess.square_rank(king), chess.square_file(king)
            if kr == back and kf in (2, 6):
                features['development'] += sign * 18
            elif kr == back and kf in (3, 4) and not (
                board.has_kingside_castling_rights(color)
                or board.has_queenside_castling_rights(color)
            ):
                features['king_safety'] -= sign * 25
        for kind in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            for sq in board.pieces(kind, color):
                if board.is_attacked_by(not color, sq) and not board.is_attacked_by(color, sq):
                    features['hanging_pieces'] -= sign * min(40, PIECE_VALUES[kind] // 12)
    return features


def evaluate(board: chess.Board, weights: dict[str, float] | None = None) -> int:
    """Return score relative to side-to-move; trained features are bounded."""
    features = evaluate_components(board)
    if weights:
        score = features['material'] + sum(features[k] * weights.get(k, 1.0)
                                           for k in LEARNABLE_FEATURES)
    else:
        score = sum(features.values())
    return round(score) if board.turn == chess.WHITE else -round(score)


class Engine:
    def __init__(self, hash_mb: int = 32, book_path: str | Path = "data/opening_book.json",
                 learning_path: str | Path = "data/approved_model.json",
                 memory_path: str | Path = "data/position_memory.json",
                 stockfish_memory_path: str | Path = "data/stockfish19_position_memory.json",
                 learned_eval_path: str | Path = "data/learned_eval_v05_candidate.json"):
        self.hash_mb = max(1, hash_mb)
        self.table: dict[int, TTEntry] = {}
        self.killers: dict[int, list[chess.Move]] = {}
        self.nodes = 0
        self.deadline: float | None = None
        self.stop_event = threading.Event()
        self.book_path = Path(book_path)
        self.own_book = True
        self.learning_enabled = True
        self.learning_path = Path(learning_path)
        self._learning: dict | None = None
        self._book: dict | None = None
        self.memory_path = Path(memory_path)
        self.memory_enabled = True
        self._memory: dict | None = None
        self.stockfish_memory_path = Path(stockfish_memory_path)
        self.stockfish_memory_enabled = True
        self._stockfish_memory: dict | None = None
        self._stockfish_pattern_index: dict | None = None
        self.learned_eval_enabled = False  # Candidate OFF until independent playing validation.
        self.learned_eval_path = Path(learned_eval_path)
        self._learned_evaluator = None

    def new_game(self) -> None:
        self.table.clear()
        self.killers.clear()
        self._learning = None  # Approved model updates are reloaded between games.
        self._memory = None  # New memory database becomes visible next game.
        self._stockfish_memory = None
        self._stockfish_pattern_index = None
        self._learned_evaluator = None

    def _load_book(self) -> dict:
        if self._book is None:
            try:
                raw = json.loads(self.book_path.read_text(encoding="utf-8"))
                self._book = raw.get("positions", {})
            except (OSError, ValueError):
                self._book = {}
        return self._book

    def _load_learning(self) -> dict:
        if self._learning is None:
            try:
                raw = json.loads(self.learning_path.read_text(encoding='utf-8'))
                if raw.get('schema') != 1:
                    raise ValueError('Unsupported learning schema')
                self._learning = raw
            except (OSError, ValueError, TypeError):
                self._learning = {'weights': {}, 'opening_moves': {}}
        return self._learning

    def memory_moves(self, board: chess.Board) -> list[tuple[chess.Move, int]]:
        """Look up exact studied positions; never trust a stored move blindly."""
        if not self.memory_enabled:
            return []
        if self._memory is None:
            try:
                raw = json.loads(self.memory_path.read_text(encoding='utf-8'))
                if raw.get('schema') != 1 or not isinstance(raw.get('positions'), dict):
                    raise ValueError('Unsupported position-memory schema')
                self._memory = raw
            except (OSError, ValueError, TypeError):
                self._memory = {'schema': 1, 'positions': {}}
        from .position_memory import legal_memory_moves
        return legal_memory_moves(board, self._memory)

    def _stockfish_preferred(self, board: chess.Board) -> chess.Move | None:
        """Recall independently reconciled Stockfish 19 position evidence.

        The overlay never bypasses normal legal-move checks or alpha-beta:
        root search evaluates this move alongside every alternative.
        """
        if not self.stockfish_memory_enabled or not self.memory_enabled:
            return None
        if self._stockfish_memory is None:
            try:
                raw = json.loads(self.stockfish_memory_path.read_text(encoding='utf-8'))
                if raw.get('schema') != 1 or not isinstance(raw.get('positions'), dict):
                    raise ValueError('Invalid Stockfish evidence schema')
                self._stockfish_memory = raw
            except (OSError, ValueError, TypeError):
                self._stockfish_memory = {'positions': {}}
        entry = self._stockfish_memory['positions'].get(book_key(board))
        if not isinstance(entry, dict):
            return None
        uci = entry.get('preferred_move')
        if not isinstance(uci, str):
            return None
        try:
            move = chess.Move.from_uci(uci)
            return move if move in board.legal_moves else None
        except ValueError:
            return None

    def _pattern_recalled(self, board: chess.Board) -> list[tuple[chess.Move, int]]:
        """Use *conservative* same-pawn-and-material patterns as search hints.

        Near positions are not identical positions: no borrowed move is played
        without being legal, and completed root search still scores every move.
        """
        if not (self.stockfish_memory_enabled and self.memory_enabled):
            return []
        if self._stockfish_memory is None:
            self._stockfish_preferred(board)  # Lazy-load the certified overlay.
        if self._stockfish_pattern_index is None:
            from .position_patterns import build_index
            self._stockfish_pattern_index = build_index(
                self._stockfish_memory.get('positions', {}))
        from .position_patterns import pattern_candidates
        return pattern_candidates(board, self._stockfish_pattern_index)

    def _static_fallback(self, board: chess.Board, moves: list[chess.Move]) -> chess.Move:
        """Never default to the first/memorized move when no iteration finishes."""
        best = (-INF, '', moves[0])
        for move in moves:
            board.push(move)
            try:
                if board.is_checkmate():
                    score = MATE
                else:
                    score = -self.evaluation(board)
            finally:
                board.pop()
            candidate = (score, move.uci(), move)
            if candidate[:2] > best[:2]:
                best = candidate
        return best[2]

    def book_move(self, board: chess.Board) -> chess.Move | None:
        if not self.own_book:
            return None
        key = book_key(board)
        choices = self._load_book().get(key, {})
        learned = (self._load_learning().get('opening_moves', {}).get(key, {})
                   if self.learning_enabled else {})
        candidates = set(choices) | set(learned)
        scores = []
        for uci in candidates:
            try:
                move = chess.Move.from_uci(uci)
                if move not in board.legal_moves:
                    continue
            except ValueError:
                continue
            counts = learned.get(uci, {})
            visits = max(0, int(counts.get('visits', 0)))
            reward = float(counts.get('reward_sum', 0))
            # Historical counts are prior, match outcomes are incremental evidence.
            # No reliance on Stockfish's move suggestions or evaluation.
            score = .13 * math.log1p(choices.get(uci, 0))
            # Legacy outcome rewards are extremely noisy; use only adequately
            # sampled moves and cap their impact against historical evidence.
            if visits >= 12:
                score += max(-0.15, min(0.15, 0.15 * reward / visits))
            scores.append((score, uci, move))
        if scores:
            return max(scores, key=lambda item: (item[0], item[1]))[2]
        return None

    def evaluation(self, board: chess.Board) -> int:
        if self.learned_eval_enabled:
            if self._learned_evaluator is None:
                from .learned_eval import LinearEvaluator
                self._learned_evaluator = LinearEvaluator.load(self.learned_eval_path)
            return self._learned_evaluator.evaluate(board)
        weights = self._load_learning().get('weights', {}) if self.learning_enabled else {}
        return evaluate(board, weights)

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
        if self.nodes % 32 == 0:
            self._check_time()
        if board.is_checkmate():
            return -MATE + ply
        if self._drawn(board):
            return 0
        in_check = board.is_check()
        stand_pat = self.evaluation(board)
        if not in_check:
            if stand_pat >= beta:
                return beta
            alpha = max(alpha, stand_pat)
        if qdepth >= 8 and not in_check:
            return alpha
        if qdepth >= 12 and in_check:
            # At the emergency horizon, standing pat in check is illegal.
            # Score *legal evasions* rather than an attacked-king position.
            legal = list(board.legal_moves)
            if not legal:
                return -MATE + ply
            best = -INF
            for evasion in legal:
                board.push(evasion)
                try:
                    val = MATE - ply - 1 if board.is_checkmate() else -self.evaluation(board)
                finally:
                    board.pop()
                best = max(best, val)
                alpha = max(alpha, val)
                if alpha >= beta:
                    break
            return best
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
        if self.nodes % 32 == 0:
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
        # Load memory before starting the thinking clock; I/O is not search.
        self.deadline = None
        if board.is_game_over(claim_draw=True):
            return SearchResult(None)
        recalled = self.memory_moves(board) if allow_book else []
        sf_preferred = self._stockfish_preferred(board) if allow_book else None
        if sf_preferred is not None:
            # This is a search preference, not a forced move. Root alpha-beta
            # still rejects it when it scores more than 20cp below the best.
            existing = [(m, n) for m, n in recalled if m != sf_preferred]
            recalled = [(sf_preferred, max([n for _, n in existing] or [0]) + 100000)] + existing
        pattern_only = False
        if allow_book and not recalled:
            # Approximate recall is ordering evidence ONLY, never a move override.
            recalled = self._pattern_recalled(board)
            pattern_only = bool(recalled)
        if allow_book and not recalled:
            bm = self.book_move(board)
            if bm:
                # Opening choices are historical priors, not proof of safety.
                # Previously they bypassed tactical search entirely.
                recalled = [(bm, 1)]
        legal = list(board.legal_moves)
        if not legal:
            return SearchResult(None)
        # Recalled moves have priority for examination, not automatic play.
        fallback = self._static_fallback(board, legal)
        result = SearchResult(fallback, score=0, depth=0)
        self.deadline = (time.monotonic() + max(0.01, time_limit)
                         if time_limit is not None else None)
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
                scores = {}
                ordered = self._ordered(board, legal, 0, preferred.move if preferred else result.move)
                if recalled:
                    # Examine known master choices first to improve alpha-beta ordering.
                    master_order = {m: n for m, n in recalled}
                    ordered.sort(key=lambda m: (m in master_order, master_order.get(m, 0)), reverse=True)
                for move in ordered:
                    board.push(move)
                    try:
                        score = -self._negamax(board, current_depth - 1, -beta, -original_alpha, 1)
                    finally:
                        board.pop()
                    scores[move] = score
                    if score > best_score:
                        best_score, best_move = score, move
                    original_alpha = max(original_alpha, score)
                if best_move is None:
                    break
                if recalled and not pattern_only:
                    from .position_memory import choose_safe_recalled_move
                    master_choice = choose_safe_recalled_move(recalled, scores, best_score)
                    if master_choice is not None:
                        best_move = master_choice
                self.table[key] = TTEntry(current_depth, best_score, 'exact', best_move)
                pv = self._pv(board, current_depth)
                result = SearchResult(best_move, scores[best_move], current_depth, self.nodes, pv or (best_move,))
                if info:
                    info(result)
                if abs(best_score) >= MATE - 100:
                    break
            except SearchTimeout:
                break
        result.nodes = self.nodes
        return result
