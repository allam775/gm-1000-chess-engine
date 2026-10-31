"""Universal Chess Interface (UCI) adapter for GM-1000."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import chess
from .search import Engine, MATE, SearchResult


class UCI:
    def __init__(self) -> None:
        self.board = chess.Board()
        self.engine = Engine(book_path=Path(__file__).resolve().parents[1] / 'data/opening_book.json',
                             learning_path=Path(__file__).resolve().parents[1] / 'data/learning_state.json')
        self.worker: threading.Thread | None = None
        self.print_lock = threading.Lock()

    def output(self, msg: str) -> None:
        with self.print_lock:
            print(msg, flush=True)

    def stop(self) -> None:
        if self.worker and self.worker.is_alive():
            self.engine.stop_event.set()
            self.worker.join(timeout=5)
        self.worker = None

    def go(self, args: list[str]) -> None:
        self.stop()
        params: dict[str, int] = {}
        flags: set[str] = set()
        for i, item in enumerate(args):
            if item in ('infinite', 'ponder'):
                flags.add(item)
            if item in ('movetime', 'depth', 'wtime', 'btime', 'winc', 'binc', 'movestogo'):
                if i + 1 < len(args):
                    try:
                        params[item] = max(0, int(args[i + 1]))
                    except ValueError:
                        pass
        depth = max(1, min(64, params.get('depth', 64)))
        if 'movetime' in params:
            limit = max(0.01, params['movetime'] / 1000)
        elif 'infinite' in flags or ('depth' in params and 'wtime' not in params and 'btime' not in params):
            limit = None
        elif 'wtime' in params or 'btime' in params:
            millis = params.get('wtime' if self.board.turn else 'btime', 1000)
            increment = params.get('winc' if self.board.turn else 'binc', 0)
            limit = max(0.01, min(millis * 0.7, millis / max(12, params.get('movestogo', 30)) + increment * .6) / 1000)
        else:
            limit = 0.5
        snapshot = self.board.copy(stack=True)
        self.engine.stop_event.clear()

        def report(r: SearchResult) -> None:
            score = (f'mate {max(1, (MATE - abs(r.score) + 1) // 2) * (1 if r.score > 0 else -1)}'
                     if abs(r.score) >= MATE - 100 else f'cp {r.score}')
            pv = ' '.join(m.uci() for m in r.pv)
            self.output(f'info depth {r.depth} nodes {r.nodes} score {score} pv {pv}')

        def run() -> None:
            try:
                result = self.engine.search(snapshot, time_limit=limit, depth=depth, info=report)
                if result.book:
                    self.output('info string selected opening book move')
                self.output('bestmove ' + (result.move.uci() if result.move else '0000'))
            except Exception as exc:
                self.output(f'info string engine error {type(exc).__name__}: {exc}')
                safe = next(iter(snapshot.legal_moves), None)
                self.output('bestmove ' + (safe.uci() if safe else '0000'))
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def process(self, line: str) -> bool:
        parts = line.strip().split()
        if not parts:
            return True
        command = parts[0]
        if command == 'uci':
            self.output('id name GM-1000 0.1')
            self.output('id author GM-1000 project')
            self.output('option name Hash type spin default 32 min 1 max 512')
            self.output('option name OwnBook type check default true')
            self.output('option name Learning type check default true')
            self.output('uciok')
        elif command == 'isready':
            self.output('readyok')
        elif command == 'ucinewgame':
            self.stop()
            self.engine.new_game()
            self.board.reset()
        elif command == 'setoption':
            self.stop()
            lower = line.lower()
            if 'name hash' in lower and ' value ' in lower:
                try:
                    self.engine.hash_mb = min(512, max(1, int(lower.split(' value ')[-1].strip())))
                except ValueError:
                    pass
            if 'name learning' in lower and ' value ' in lower:
                self.engine.learning_enabled = lower.split(' value ')[-1].strip() in ('1', 'true', 'yes', 'on')
            if 'name ownbook' in lower and ' value ' in lower:
                self.engine.own_book = lower.split(' value ')[-1].strip() in ('1', 'true', 'yes', 'on')
        elif command == 'position':
            self.stop()
            try:
                if len(parts) < 2:
                    raise ValueError('position missing type')
                if parts[1] == 'startpos':
                    new_board = chess.Board()
                    move_at = 2
                elif parts[1] == 'fen':
                    move_at = parts.index('moves') if 'moves' in parts else len(parts)
                    new_board = chess.Board(' '.join(parts[2:move_at]))
                else:
                    raise ValueError('expected startpos or fen')
                if move_at < len(parts) and parts[move_at] == 'moves':
                    for uci in parts[move_at + 1:]:
                        new_board.push_uci(uci)
                self.board = new_board
            except (ValueError, chess.IllegalMoveError) as exc:
                self.output(f'info string invalid position: {exc}')
        elif command == 'go':
            self.go(parts[1:])
        elif command == 'stop':
            self.stop()
        elif command == 'quit':
            self.stop()
            return False
        return True


def main() -> None:
    uci = UCI()
    for line in sys.stdin:
        if not uci.process(line):
            break
    uci.stop()


if __name__ == '__main__':
    main()
