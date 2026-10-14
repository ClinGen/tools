#!/usr/bin/env python

import sys

from dotenv import load_dotenv


def main() -> None:  # ruff: ignore[undocumented-public-function]
    # Load environment variables from the .env file.
    load_dotenv()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        error_message = (
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you forget to"
            "activate a virtual environment?"
        )
        raise ImportError(error_message) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
