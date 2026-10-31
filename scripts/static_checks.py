"""Offline structural checks that require only Python's standard library.

Not a substitute for tests/test_core.py or an actual Stockfish arena run.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    required = [
        'requirements.txt', 'README.md', 'engine/search.py', 'engine/uci.py',
        'engine/__main__.py', 'scripts/build_book.py', 'scripts/arena.py',
        '.github/workflows/ci.yml', '.github/workflows/build-book.yml',
        '.github/workflows/arena.yml', 'tests/test_core.py',
    ]
    for name in required:
        assert (ROOT / name).is_file(), f'Missing {name}'
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        source = path.read_text(encoding='utf-8')
        assert '\non:' in source and '\njobs:' in source
    print(f'PASS: {len(required)} required files, all Python AST and 3 workflow structure checks')


if __name__ == '__main__':
    run()
