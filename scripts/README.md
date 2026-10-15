# `scripts`

This directory holds standalone Python scripts for developer tasks that aren't part of
the Django app. Run them from the root of the repository, usually through a `just`
recipe.

### `env_check.py`

Checks that `.env` and `.env.example` have the same keys and lists any key found in
only one of them. Run it with `just env-check`; `just ci` and `just pre-commit` run it
too.

### `test_env_check.py`

Tests `env_check.py` against temporary `.env` and `.env.example` files.
