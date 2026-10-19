#!/usr/bin/env python3
"""Install the release NSIS package and verify its payload on an isolated runner."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    with path.open('rb') as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('The installer check requires a Windows runner.')
    root = Path(__file__).resolve().parents[1]
    installers = list((root / 'dist/desktop').glob('*-Windows-x64-Setup.exe'))
    if len(installers) != 1:
        raise SystemExit('Expected exactly one release installer.')
    target = args.target.resolve()
    if target.exists():
        raise SystemExit('Use a new isolated installation directory.')
    target.parent.mkdir(parents=True, exist_ok=True)
    source = root / 'dist/desktop/win-unpacked'
    expected = {p.relative_to(source): digest(p) for p in source.rglob('*') if p.is_file()}
    if not expected:
        raise SystemExit('The unpacked payload is missing.')
    # NSIS requires /D last and unquoted, even when the path contains spaces.
    subprocess.run('"' + str(installers[0]) + '" /S /D=' + str(target), check=True, timeout=180)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        missing = [str(p) for p in expected if not (target / p).is_file()]
        if not missing:
            break
        time.sleep(1)
    if missing:
        raise SystemExit('Installer omitted files: ' + ', '.join(missing))
    mismatched = [str(p) for p, value in expected.items() if digest(target / p) != value]
    if mismatched:
        raise SystemExit('Installed payload differs: ' + ', '.join(mismatched))
    print('Verified complete installed payload:', len(expected), 'files at', target)


if __name__ == '__main__':
    main()
