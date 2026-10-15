"""env_check.py checks that .env and .env.example have the same keys.

The .env file holds secrets, so Git ignores it. .env.example is tracked and lists the
same keys with empty values, so everyone can see which keys .env needs. Run this script
with `just env-check` to find keys that are in one file but not the other.
"""

import argparse
import re
import sys
from pathlib import Path

# A key is the name before the first "=", optionally after "export ".
KEY_PATTERN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def read_keys(path: Path) -> set[str]:
    """Reads the keys from a .env-style file, ignoring blank lines and comments.

    Args:
        path: The file to read.

    Returns:
        The keys in the file.
    """
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = KEY_PATTERN.match(line.strip())
        if match:
            keys.add(match.group(1))
    return keys


def main(argv: list[str] | None = None) -> int:
    """Compares the keys in .env and .env.example and prints any differences.

    Args:
        argv: Command line arguments. Defaults to sys.argv[1:].

    Returns:
        0 if both files have the same keys, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--example", type=Path, default=Path(".env.example"))
    args = parser.parse_args(argv)

    for path in (args.env, args.example):
        if not path.is_file():
            print(f"{path} doesn't exist.")
            return 1

    env_keys = read_keys(args.env)
    example_keys = read_keys(args.example)
    if env_keys == example_keys:
        print(f"{args.env} and {args.example} have the same keys.")
        return 0

    for path, missing in (
        (args.example, env_keys - example_keys),
        (args.env, example_keys - env_keys),
    ):
        if missing:
            print(f"Missing from {path}:")
            for key in sorted(missing):
                print(f"  {key}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
