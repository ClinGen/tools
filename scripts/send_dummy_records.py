"""Sends random dummy records to a running CSS, as the VCI would.

Each record is different every run but valid for the CSS's API. The script POSTs them
to /css/api/v1/records with the API key in CSS_DUMMY_API_KEY, read from .env, and
prints what the CSS did with each one. With --resend, it then sends some of them again
with a new classification, so you can watch a waiting record get replaced.

Usage:
    uv run scripts/send_dummy_records.py [--count 5] [--url http://localhost:8000]
        [--resend]
"""

import argparse
import os
import random
import sys
from copy import deepcopy
from datetime import date, timedelta
from http import HTTPStatus
from typing import Any

import requests
from dotenv import load_dotenv

# Made-up affiliations, until the AS can supply its VCEPs. IDs are AS-style.
AFFILIATIONS = [
    {"id": 10901, "name": "Cardiomyopathy VCEP"},
    {"id": 10902, "name": "TP53 VCEP"},
    {"id": 10903, "name": "Malignant Hyperthermia Susceptibility VCEP"},
    {"id": 10904, "name": "Phenylketonuria VCEP"},
    {"id": 10905, "name": "CDH1 VCEP"},
]

# Each variant's gene, an HGVS expression on GRCh38, and a condition it's tied to.
VARIANTS = [
    ("MYH7", "NM_000257.4:c.1208G>A", "MONDO:0024573"),
    ("MYBPC3", "NM_000256.3:c.1504C>T", "MONDO:0024573"),
    ("TP53", "NM_000546.6:c.743G>A", "MONDO:0007903"),
    ("RYR1", "NM_000540.3:c.1840C>T", "MONDO:0007783"),
    ("PAH", "NM_000277.3:c.1222C>T", "MONDO:0009861"),
    ("CDH1", "NM_004360.5:c.1137G>A", "MONDO:0007648"),
    ("BRCA1", "NC_000017.11:g.43045712T>C", "MONDO:0011450"),
]

CLASSIFICATIONS = [
    "Pathogenic",
    "Likely pathogenic",
    "Uncertain significance",
    "Likely benign",
    "Benign",
]

INHERITANCE = [
    "Autosomal dominant inheritance",
    "Autosomal recessive inheritance",
    "X-linked inheritance",
]

CRITERIA = ["PVS1", "PS3", "PM1", "PM2", "PP3", "BS1", "BP4"]

API_KEY_VARIABLE = "CSS_DUMMY_API_KEY"

TIMEOUT_SECONDS = 30


def dummy_body(rng: random.Random) -> dict[str, Any]:
    """Returns a random request body: an affiliation and one germline record.

    Args:
        rng: Where the randomness comes from, so tests can seed it.

    Returns:
        The body, as the VCI would send it.
    """
    gene, hgvs, condition = rng.choice(VARIANTS)
    local_id = f"dummy-{rng.getrandbits(32):08x}"
    evaluated = date(2026, 1, 1) + timedelta(days=rng.randrange(300))
    record: dict[str, Any] = {
        "recordStatus": "novel",
        "localID": local_id,
        "localKey": local_id,
        "submittedAssembly": "GRCh38",
        "variantSet": {"variant": [{"hgvs": hgvs, "gene": [{"symbol": gene}]}]},
        "conditionSet": {"condition": [{"db": "MONDO", "id": condition}]},
        "germlineClassification": {
            "germlineClassificationDescription": rng.choice(CLASSIFICATIONS),
            "modeOfInheritance": rng.choice(INHERITANCE),
            "dateLastEvaluated": evaluated.isoformat(),
            "comment": "Criteria met: " + ", ".join(rng.sample(CRITERIA, 3)) + ".",
        },
        "observedIn": [
            {
                "alleleOrigin": "germline",
                "affectedStatus": "not provided",
                "collectionMethod": "curation",
            }
        ],
    }
    if rng.random() < 0.2:
        record["recordStatus"] = "update"
        record["clinvarAccession"] = f"SCV{rng.randrange(10**9):09d}"
    return {"affiliation": rng.choice(AFFILIATIONS), "record": record}


def resent(body: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Returns the body again with a different classification, as if it was revised.

    Returns:
        A copy of the body with a new classification.
    """
    again = deepcopy(body)
    classification = again["record"]["germlineClassification"]
    old = classification["germlineClassificationDescription"]
    choices = [c for c in CLASSIFICATIONS if c != old]
    classification["germlineClassificationDescription"] = rng.choice(choices)
    return again


class SendError(Exception):
    """A problem sending records, with a message for the person running the script."""


def send(url: str, key: str, body: dict[str, Any]) -> str:
    """POSTs one body to the CSS.

    Returns:
        A line saying what the CSS did with the record.

    Raises:
        SendError: If the CSS can't be reached, rejects the key, or rejects the record.
    """
    try:
        response = requests.post(
            f"{url.rstrip('/')}/css/api/v1/records",
            json=body,
            headers={"X-API-Key": key},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        message = f"Couldn't reach the CSS at {url}. Is it running? ({error})"
        raise SendError(message) from error
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        message = f"The CSS didn't accept the API key in {API_KEY_VARIABLE}."
        raise SendError(message)
    if response.status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
        message = f"The CSS returned {response.status_code}: {response.text}"
        raise SendError(message)
    result = response.json()
    what = "new" if response.status_code == HTTPStatus.CREATED else "replaced"
    record = body["record"]
    return (
        f"{result['slug']} ({what}, {result['status']}): {record['localID']}, "
        f"{body['affiliation']['name']}, "
        f"{record['germlineClassification']['germlineClassificationDescription']}"
    )


def main(argv: list[str] | None = None) -> int:
    """Sends the dummy records.

    Returns:
        0 if every record was sent, or 1 if something went wrong.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=5, help="How many records.")
    parser.add_argument(
        "--url", default="http://localhost:8000", help="Where the CSS is running."
    )
    parser.add_argument(
        "--resend",
        action="store_true",
        help="Send about half of the records again with a new classification.",
    )
    args = parser.parse_args(argv)
    load_dotenv()
    key = os.environ.get(API_KEY_VARIABLE, "")
    if not key:
        print(
            f"Set {API_KEY_VARIABLE} in .env to a CSS API key. Make one in the Django "
            "admin under API Keys.",
            file=sys.stderr,
        )
        return 1
    rng = random.Random()
    bodies = [dummy_body(rng) for _ in range(args.count)]
    if args.resend:
        bodies += [resent(body, rng) for body in bodies[: max(1, args.count // 2)]]
    try:
        for body in bodies:
            print(send(args.url, key, body))
    except SendError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
