"""Polls ClinVar for submission statuses until it's stopped.

systemd runs this next to Gunicorn. It sleeps CSS_POLL_SLEEP_SECONDS between passes,
and on SIGTERM it finishes the submission it's polling and exits.
"""

import logging
import signal
import time
from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from clinvar_submission_service.polling import Poller

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Polls ClinVar for the status of each submission that's due."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Adds --once, which runs one pass and exits."""
        parser.add_argument(
            "--once", action="store_true", help="Run one pass, then exit."
        )

    def handle(self, *_args: object, **options: Any) -> None:  # ruff: ignore[any-type] (Django's signature.)
        """Runs passes until SIGTERM, or one pass with --once."""
        poller = Poller()
        signal.signal(signal.SIGTERM, lambda *_: poller.stop())
        logger.info("Polling ClinVar.")
        while not poller.stopping:
            try:
                polled = poller.run_pass()
            except Exception:
                # The loop must outlive any one pass's failure, such as a missing key.
                logger.exception("A pass of the poller failed.")
                polled = 0
            if polled:
                logger.info("Polled %d submissions.", polled)
            if options["once"]:
                break
            time.sleep(settings.CSS_POLL_SLEEP_SECONDS)
        logger.info("Stopped polling ClinVar.")
