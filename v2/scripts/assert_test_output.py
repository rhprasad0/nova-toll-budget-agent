"""Fail if test output contains a forbidden literal, including on read errors."""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("literal")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if str(args.literal).encode() in Path(args.output).read_bytes():
        raise SystemExit("Forbidden content found in test output")


if __name__ == "__main__":
    main()
