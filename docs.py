"""docs.py helps keep documentation up-to-date.

The documentation system works like this:
- Each significant directory in the project has a README.
- The README describes the purpose of the directory at a high level.
- The README describes each file in the directory at a high level.

A configuration file named docs.json should live at the root directory of your project.
The docs.json configuration file must contain a list of directories and a list of ignore
patterns. The directories mentioned in docs.json are the directories that contain a
README. The ignore patterns specify files and directories to ignore.
"""

import argparse
import json
from pathlib import Path


def _is_ignored(rel_path: Path, ignore: list[str]) -> bool:
    """Reports whether a path should be skipped based on the ignore patterns.

    A path is ignored if any of its parts equals an ignore pattern or if the
    full path matches an ignore pattern as a glob.

    Args:
        rel_path: A path relative to the directory being documented.
        ignore: Patterns of files and directories to skip.

    Returns:
        True if the path should be ignored, False otherwise.
    """
    parts = rel_path.parts
    for pattern in ignore:
        if pattern in parts:
            return True
        if rel_path.full_match(pattern):
            return True
    return False


def _collect_files(dir_path: Path, ignore: list[str]) -> list[str]:
    """Collects the files in a directory that should be mentioned in the README.

    Args:
        dir_path: The directory to walk.
        ignore: Patterns of files and directories to skip.

    Returns:
        A sorted list of file paths relative to dir_path.
    """
    files: list[str] = []
    for path in sorted(dir_path.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "README.md":
            continue
        rel = path.relative_to(dir_path)
        if _is_ignored(rel, ignore):
            continue
        files.append(str(rel))
    return files


def generate(directories: list[str], ignore: list[str]) -> None:
    """Generates a README for each given directory.

    Args:
        directories: Paths to directories that should get a README.
        ignore: Patterns of files and directories to skip.
    """
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.is_dir():
            print(f"Error: {directory} is not a directory.")
            return
        readme_path = dir_path / "README.md"
        files = _collect_files(dir_path, ignore)
        lines: list[str] = [
            f"# `{dir_path.name}`",
            "",
            "(A high-level overview of the directory and its contents goes here.)",
            "",
        ]
        for f in files:
            lines.append(f"### `{f}`")
            lines.append("")
            lines.append("(Insert file description here.)")
            lines.append("")
        readme_path.write_text("\n".join(lines).rstrip() + "\n")


def check(directories: list[str], ignore: list[str]) -> bool:
    """Checks that each directory's README mentions all non-ignored files.

    Args:
        directories: Paths to directories whose READMEs should be checked.
        ignore: Patterns of files and directories to skip.

    Returns:
        True if every README mentions all of its directory's non-ignored files,
        False otherwise.
    """
    all_ok = True
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.is_dir():
            print(f"Error: {directory} is not a directory.")
            all_ok = False
            continue
        readme_path = dir_path / "README.md"
        if not readme_path.is_file():
            print(f"Error: {readme_path} does not exist.")
            all_ok = False
            continue
        readme_text = readme_path.read_text()
        files = _collect_files(dir_path, ignore)
        missing = [f for f in files if f not in readme_text]
        if missing:
            all_ok = False
            print(f"{directory}: missing mentions for:")
            for f in missing:
                print(f"  {f}")
        else:
            print(f"{directory}: OK")
    return all_ok


def main() -> int:
    """Entry point for the script.

    Returns:
        0 if successful, 1 otherwise.
    """
    # Load the configuration file. The configuration file lists the significant
    # directories in the project, and it tells the script which directories and files
    # to ignore.
    config_path = Path.cwd() / "docs.json"
    if not config_path.is_file():
        print(f"Error: Unable to find config file in {Path.cwd()}.")
        return 1
    with config_path.open("r") as f:
        config = json.load(f)

    # Set up the command line argument parser.
    parser = argparse.ArgumentParser(
        prog="docs.py",
        description="docs.py helps keep documentation up-to-date.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate_parser = subparsers.add_parser(
        "generate",
        help=(
            "For each significant directory listed in docs.json, creates a README "
            "with a blank description of each file in the directory."
        ),
    )
    generate_group = generate_parser.add_mutually_exclusive_group(required=True)
    generate_group.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Generate a README for every directory listed in docs.json.",
    )
    generate_group.add_argument(
        "-d",
        "--directory",
        help="Generate a README for only the given directory.",
    )
    check_parser = subparsers.add_parser(
        "check",
        help=(
            "For each significant directory, makes sure all files in the directory "
            "are mentioned in the directory's README."
        ),
    )
    check_group = check_parser.add_mutually_exclusive_group(required=True)
    check_group.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Check the README for every directory listed in docs.json.",
    )
    check_group.add_argument(
        "-d",
        "--directory",
        help="Check the README for only the given directory.",
    )

    # Decide what to do based on the user's input.
    args = parser.parse_args()
    directories = config.get("directories", [])
    ignore = config.get("ignore", [])
    match args.command:
        case "generate":
            targets = directories if args.all else [args.directory]
            generate(targets, ignore)
        case "check":
            if args.all:
                targets = directories
            else:
                configured = {str(Path(d)) for d in directories}
                if str(Path(args.directory)) not in configured:
                    print(
                        f"Error: {args.directory} is not in the list of "
                        f"directories in docs.json."
                    )
                    return 1
                targets = [args.directory]
            if not check(targets, ignore):
                return 1

    return 0


if __name__ == "__main__":
    main()
