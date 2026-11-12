# `scripts`

This directory holds standalone Python scripts for developer tasks that aren't part of
the Django app. Run them from the root of the repository, usually through a `just`
recipe.

### `env_check.py`

Checks that `.env` and `.env.example` have the same keys and lists any key found in
only one of them. Run it with `just env-check`; `just ci` and `just pre-commit` run it
too.

### `send_dummy_records.py`

Sends random dummy records to a running CSS, as the VCI would, so you can try the CSS's
workflow locally. Each run makes different records, valid for the CSS's API, from a
small pool of made-up VCEPs, genes, and conditions; about one in five is an update with
a made-up SCV. It POSTs them to `/css/api/v1/records` with the API key in
`CSS_DUMMY_API_KEY` and prints each record's ID and whether it's new or replaced. Run
it with `just django-send-dummy-records`, adding `--count`, `--url`, or `--resend`,
which sends about half of them again with a new classification.

### `test_env_check.py`

Tests `env_check.py` against temporary `.env` and `.env.example` files.

### `test_send_dummy_records.py`

Tests `send_dummy_records.py`: that its records are valid for the CSS's API, include
updates, and differ between runs; that a resent record keeps its local ID; and, with
`requests` mocked, that it sends the key, reports new and replaced records, and exits
with a plain message for a missing key, a rejected key, or a CSS it can't reach.
