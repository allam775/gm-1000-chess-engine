"""Select up to 1000 distinct historical games and count opening moves.

Downloads ZIP archives published by PGN Mentor, or reads local .zip/.pgn
collections when --source-dir is specified. See README for selection caveats.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import statistics
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.search import book_key  # noqa: E402

PLAYERS = ("Carlsen", "Kasparov", "Fischer", "Karpov", "Anand",
           "Tal", "Capablanca", "Morphy", "Botvinnik", "Alekhine")
BASE_URL = "https://www.pgnmentor.com/players/"


@dataclass
class Candidate:
    source: str
    headers: dict[str, str]
    moves: tuple[str, ...]
    fingerprint: str
    quality: float


def quality_score(headers: dict[str, str], move_count: int) -> float:
    """Transparent heuristic, not an objective 'greatness' ranking."""
    event = headers.get('Event', '').lower()
    event_bonus = sum(12 for w in ('world', 'championship', 'candidates', 'olympiad',
                                    'linares', 'wijk', 'tata', 'sinquefield') if w in event)
    ratings = []
    for key in ('WhiteElo', 'BlackElo'):
        try:
            r = int(headers.get(key, ''))
            if 1800 <= r <= 3100:
                ratings.append(r)
        except ValueError:
            pass
    rating_bonus = ((statistics.mean(ratings) - 2000) / 40 if ratings else 0)
    result_bonus = 5 if headers.get('Result') in ('1-0', '0-1') else 0
    return min(move_count, 160) * .25 + event_bonus + rating_bonus + result_bonus


def _local_source(path: Path) -> str:
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            names = sorted((n for n in archive.namelist() if n.lower().endswith('.pgn')))
            if not names:
                raise ValueError(f'No PGN in {path}')
            return archive.read(names[0]).decode('utf-8-sig', errors='replace')
    return path.read_text(encoding='utf-8-sig', errors='replace')


def get_source(player: str, source_dir: Path | None, cache_dir: Path) -> str:
    if source_dir is not None:
        for suffix in ('.zip', '.pgn'):
            file = source_dir / (player + suffix)
            if file.is_file():
                return _local_source(file)
        raise FileNotFoundError(f'No local {player}.zip or {player}.pgn in {source_dir}')
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (player + '.zip')
    if not path.exists():
        url = BASE_URL + player + '.zip'
        request = urllib.request.Request(url, headers={'User-Agent': 'GM-1000/0.1 (open-source chess research)'})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
        # Do not cache bad HTTP content or an invalid archive.
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert any(n.lower().endswith('.pgn') for n in archive.namelist())
        path.write_bytes(content)
    return _local_source(path)


def parse_candidates(pgn_text: str, player: str, cap: int) -> tuple[list[Candidate], int]:
    candidates: list[Candidate] = []
    scanned = 0
    handle = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(handle)
        if game is None:
            break
        scanned += 1
        if game.errors:
            continue
        headers = dict(game.headers)
        if headers.get('Result') not in ('1-0', '0-1', '1/2-1/2'):
            continue
        if game.board().fen() != chess.STARTING_FEN:
            continue
        moves = tuple(move.uci() for move in game.mainline_moves())
        if len(moves) < 40:  # 20 moves/side-count? 40 ply = 20 full moves.
            continue
        signature = hashlib.sha256((' '.join(moves)).encode('ascii')).hexdigest()
        candidates.append(Candidate(player, headers, moves, signature, quality_score(headers, len(moves))))
    candidates.sort(key=lambda item: (-item.quality, item.fingerprint))
    # Dedup within each player before trimming.
    seen = set()
    unique = []
    for candidate in candidates:
        if candidate.fingerprint not in seen:
            unique.append(candidate)
            seen.add(candidate.fingerprint)
            if len(unique) >= cap:
                break
    return unique, scanned


def select_round_robin(by_player: dict[str, list[Candidate]], count: int) -> list[Candidate]:
    seen = set()
    selected = []
    positions = {name: 0 for name in PLAYERS}  # Missing archives are valid in a restricted GM study.
    while len(selected) < count:
        progressed = False
        for player in PLAYERS:
            games = by_player.get(player, [])
            while positions[player] < len(games):
                candidate = games[positions[player]]
                positions[player] += 1
                progressed = True
                if candidate.fingerprint not in seen:
                    selected.append(candidate)
                    seen.add(candidate.fingerprint)
                    break
            if len(selected) >= count:
                break
        if not progressed:
            break
    return selected


def create_book(selected: list[Candidate], max_plies: int = 24) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    for game in selected:
        board = chess.Board()
        for uci in game.moves[:max_plies]:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f'Corrupt move {uci} in selected game')
            counts[book_key(board)][uci] += 1
            board.push(move)
    return {
        'schema': 1,
        'selected_games': len(selected),
        'max_plies': max_plies,
        'position_count': len(counts),
        'positions': {k: dict(sorted(v.items(), key=lambda item: (-item[1], item[0])))
                      for k, v in sorted(counts.items())},
    }


def build(args: argparse.Namespace) -> dict:
    by_player = {}
    scanned = {}
    pool_size = max(200, math.ceil(args.limit / len(PLAYERS)) * 4)
    for player in PLAYERS:
        try:
            content = get_source(player, args.source_dir, args.cache_dir)
            by_player[player], scanned[player] = parse_candidates(content, player, pool_size)
            print(f'{player}: scanned {scanned[player]}, eligible pool {len(by_player[player])}', flush=True)
        except Exception as exc:
            print(f'ERROR: {player}: {exc}', file=sys.stderr, flush=True)
            if not args.allow_missing:
                raise
            by_player[player], scanned[player] = [], 0
    selected = select_round_robin(by_player, args.limit)
    if len(selected) < args.limit:
        raise RuntimeError(f'Only {len(selected)} unique eligible games found, need {args.limit}')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    book = create_book(selected, args.plies)
    (args.output_dir / 'opening_book.json').write_text(
        json.dumps(book, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    provenance = {
        'source': 'PGN Mentor player archives' if args.source_dir is None else str(args.source_dir),
        'selection_method': 'quality sort within each player, then round-robin unique move sequences',
        'requested': args.limit, 'selected': len(selected), 'scanned_by_player': scanned,
        'selected_by_player': dict(sorted(Counter(x.source for x in selected).items())),
        'items': [{
            'source': game.source, 'fingerprint_sha256': game.fingerprint,
            'event': game.headers.get('Event', ''), 'date': game.headers.get('Date', ''),
            'white': game.headers.get('White', ''), 'black': game.headers.get('Black', ''),
            'result': game.headers.get('Result', ''), 'plies': len(game.moves),
            'quality_score': round(game.quality, 2),
        } for game in selected]
    }
    (args.output_dir / 'selection_index.json').write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with (args.output_dir / 'selected_1000.pgn').open('w', encoding='utf-8') as handle:
        for record in selected:
            game = chess.pgn.Game()
            game.headers.clear()
            game.headers.update(record.headers)
            node = game
            for uci in record.moves:
                node = node.add_variation(chess.Move.from_uci(uci))
            handle.write(str(game) + '\n\n')
    print(f'Built {len(selected)} games, {book["position_count"]} positions')
    return book


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--plies', type=int, default=24)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--source-dir', type=Path, help='Use local NAME.zip or NAME.pgn archives')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'data/cache')
    parser.add_argument('--allow-missing', action='store_true', help='Skip failed source files')
    args = parser.parse_args()
    if args.limit < 1 or args.plies < 1:
        parser.error('limit and plies must be positive')
    build(args)


if __name__ == '__main__':
    main()
