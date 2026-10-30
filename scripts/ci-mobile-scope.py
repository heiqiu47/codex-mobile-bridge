#!/usr/bin/env python3
"""Select native compile checks from changed paths, including removed files."""
import argparse
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {'package.json', 'package-lock.json', '.github/workflows/tests.yml',
         '.github/workflows/mobile.yml', 'scripts/ci-mobile-scope.py',
         'scripts/ci-android-build.sh', 'tests/test_mobile_ios_build.py'}


def needs_mobile(paths):
    return any(path in FILES or path.startswith(('mobile/', 'web/hosts/', 'web/client-icons/',
                                                 'scripts/build-mobile-')) for path in paths)


def changed_paths(root, base, head):
    if not re.fullmatch(r'[0-9a-fA-F]{40}', head):
        raise ValueError('Expected an exact head commit')
    if not re.fullmatch(r'[0-9a-fA-F]{40}', base or '') or set(base) == {'0'}:
        command = ['git', 'ls-tree', '-r', '--name-only', '-z', head]
    else:
        command = ['git', 'diff', '--no-renames', '--name-only', '-z', base, head]
    return subprocess.check_output(command, cwd=root).decode().split('\0')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default=os.environ.get('BASE_SHA', ''))
    parser.add_argument('--head', default=os.environ.get('HEAD_SHA', ''))
    args = parser.parse_args()
    value = str(needs_mobile(changed_paths(ROOT, args.base, args.head))).lower()
    print('mobile=' + value)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write('mobile=' + value + '\n')


if __name__ == '__main__':
    main()
