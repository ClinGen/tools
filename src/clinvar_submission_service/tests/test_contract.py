"""Checks the client against ClinVar's real test endpoint.

These tests run only when RUN_CONTRACT_TESTS=1 and CSS_CLINVAR_API_KEY are set in the
environment. They use ClinVar's test endpoint and dry-run mode, so they never create a
submission, let alone a public one.
"""

import os
import unittest

from django.test import SimpleTestCase

from clinvar_submission_service.clients import CLINVAR_TEST_URL, ClinVarClient
from clinvar_submission_service.tests.fakes import make_content

API_KEY = os.getenv("CSS_CLINVAR_API_KEY", "")


@unittest.skipUnless(
    os.getenv("RUN_CONTRACT_TESTS") == "1" and API_KEY,
    "Set RUN_CONTRACT_TESTS=1 and CSS_CLINVAR_API_KEY to run the contract tests.",
)
class ClinVarContractTest(SimpleTestCase):
    def test_a_dry_run_reaches_clinvar_with_our_key(self):
        client = ClinVarClient(base_url=CLINVAR_TEST_URL, api_key=API_KEY)
        self.assertIsNone(client.submit(make_content(), dry_run=True))
