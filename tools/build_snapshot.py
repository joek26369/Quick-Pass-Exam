#!/usr/bin/env python3
"""Build the reviewed candidate using an explicit file allowlist."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def build(output: Path) -> None:
    names = [line.strip() for line in (ROOT / 'SNAPSHOT_FILES.txt').read_text().splitlines()
             if line.strip() and not line.startswith('#')]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate allowlist entries')
    checked = []
    for name in names:
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or '__pycache__' in rel.parts:
            raise ValueError(f'Unsafe snapshot path: {name}')
        file = ROOT / rel
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(ROOT):
            raise ValueError(f'Missing or unsafe file: {name}')
        checked.append((name, file.read_bytes()))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in checked:
                archive.writestr('quick-pass-exam/' + name, content)
    print(f'{output.name}: {len(checked)} files; sha256={hashlib.sha256(output.read_bytes()).hexdigest()}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    build(parser.parse_args().output)
