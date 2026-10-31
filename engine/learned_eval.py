"""Fast, position-based linear evaluator for GM-1000 v0.5.

Stockfish scores supervise a low-cost, symmetry-aware feature model, not a
position->move table. The runtime requires only chess, not NumPy or torch.
The model is opt-in until independent playing-strength promotion is justified.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import chess

PIECE_CP = (0, 100, 320, 335, 500, 900, 0)
PIECE_SQUARE_COUNT = 6 * 64
# Piece-square coefficients, tempo, KS rights, QS rights, bishop pair,
# isolated pawn count, doubled pawn count; all features are white minus black.
FEATURE_NAMES = [f"{name}@{chess.square_name(s)}" for name in
                 ("pawn", "knight", "bishop", "rook", "queen", "king")
                 for s in chess.SQUARES] + [
                     "tempo", "kingside_castle_rights", "queenside_castle_rights",
                     "bishop_pair", "isolated_pawns", "doubled_pawns"]
DIM = len(FEATURE_NAMES)
assert DIM == 390


def feature_vector(board: chess.Board) -> tuple[list[int], int]:
    """Symmetry-aware white-perspective sparse features + fixed material."""
    values = [0] * DIM
    material = 0
    pawn_files = [[0] * 8, [0] * 8]
    bishop_count = [0, 0]
    for sq, piece in board.piece_map().items():
        col = piece.color
        sign = 1 if col == chess.WHITE else -1
        target = sq if col == chess.WHITE else sq ^ 56
        values[(piece.piece_type - 1) * 64 + target] += sign
        material += sign * PIECE_CP[piece.piece_type]
        if piece.piece_type == chess.PAWN:
            pawn_files[int(col)][chess.square_file(sq)] += 1
        elif piece.piece_type == chess.BISHOP:
            bishop_count[int(col)] += 1
    values[384] = 1 if board.turn == chess.WHITE else -1
    for col in chess.COLORS:
        sign = 1 if col == chess.WHITE else -1
        values[385] += sign * int(board.has_kingside_castling_rights(col))
        values[386] += sign * int(board.has_queenside_castling_rights(col))
        values[387] += sign * int(bishop_count[int(col)] >= 2)
        files = pawn_files[int(col)]
        for file, count in enumerate(files):
            if count and not (files[file - 1] if file > 0 else 0) and not (files[file + 1] if file < 7 else 0):
                values[388] += sign * count
            values[389] += sign * max(0, count - 1)
    return values, material


class LinearEvaluator:
    def __init__(self, raw: dict):
        if raw.get('schema') != 1 or raw.get('architecture') != 'symmetric_linear_pst_v1':
            raise ValueError('Unsupported learned evaluator')
        weights = raw.get('weights_cp')
        if not isinstance(weights, list) or len(weights) != DIM:
            raise ValueError('Wrong feature vector length')
        if any(not isinstance(w, (int, float)) or not math.isfinite(w) or abs(w) > 300 for w in weights):
            raise ValueError('Unsafe weights')
        self.weights = tuple(float(w) for w in weights)
        self.version = raw.get('version', 'unversioned')

    @classmethod
    def load(cls, path: str | Path) -> 'LinearEvaluator':
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def evaluate(self, board: chess.Board) -> int:
        if board.is_insufficient_material():
            return 0
        features, fixed_material = feature_vector(board)
        cp = fixed_material + sum(w * x for w, x in zip(self.weights, features) if x)
        cp = max(-25000, min(25000, cp))
        return round(cp if board.turn == chess.WHITE else -cp)