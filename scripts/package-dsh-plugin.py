"""Export the credential-free local Harness plugin bundle."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.clients.deepseek.manual import export_package

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True)
    args = parser.parse_args()
    print(json.dumps(export_package(args.output_directory), ensure_ascii=False))
