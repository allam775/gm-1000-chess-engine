"""Compile the four immutable engine arms and record their exact provenance."""
import hashlib
import json
from pathlib import Path
import subprocess

from scripts.validate_v11_audit import ROOT, SHAS


def build():
    out = ROOT/'build/v11'
    out.mkdir(parents=True, exist_ok=True)
    source_hashes = {}
    for variant, sha in SHAS.items():
        source = subprocess.check_output(['git', 'show', f'{sha}:native/gm1000.cpp'], cwd=ROOT)
        path = out/f'{variant}.cpp'
        path.write_bytes(source)
        source_hashes[variant] = hashlib.sha256(source).hexdigest()
        subprocess.run(['g++', '-O3', '-DNDEBUG', '-std=c++17', '-pthread',
                        '-Wall', '-Wextra', '-Werror', '-I', str(ROOT/'native/third_party'),
                        str(path), '-o', str(out/variant)], check=True)
    provenance = dict(shas=SHAS,source_sha256=source_hashes,
        binary_sha256={v:hashlib.sha256((out/v).read_bytes()).hexdigest() for v in SHAS},
        header_sha256=hashlib.sha256((ROOT/'native/third_party/chess.hpp').read_bytes()).hexdigest(),
        compiler=subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
        flags='-O3 -DNDEBUG -std=c++17 -pthread -Wall -Wextra -Werror')
    assert len(set(source_hashes.values())) == 4
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2))


if __name__ == '__main__':
    build()
