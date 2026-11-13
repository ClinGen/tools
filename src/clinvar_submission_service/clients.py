"""Talks to the NCBI ClinVar Submission API.

Each method makes one of the calls the CSS needs: create a submission, read its status,
and download its summary report. `ClinVarClient.from_settings()` builds a client from
the CSS_ settings; tests build one around a mocked requests session. Every request sends
the service account's API key, which must never appear in a log or an error.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

CLINVAR_PRODUCTION_URL = "https://submit.ncbi.nlm.nih.gov/api/v1"

# ClinVar's test endpoint validates submissions fully but never makes them public.
CLINVAR_TEST_URL = "https://submit.ncbi.nlm.nih.gov/apitest/v1"

# How long to wait for ClinVar, in seconds, before giving up on a request.
TIMEOUT = 30


class ClinVarError(Exception):
    """A request to ClinVar that failed.

    Attributes:
        retryable: Whether trying again later might work, as it might after a timeout,
            a 429, or a 5xx, but not after a 400 or 401.
        retry_after: For a 429, how many seconds ClinVar asked us to wait, if it said.
    """

    def __init__(
        self, message: str, *, retryable: bool, retry_after: int | None = None
    ) -> None:
        """Stores whether the request is worth retrying."""
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class ClinVarStatus:
    """ClinVar's status for a submission.

    Attributes:
        status: ClinVar's status: submitted, processing, processed, or error.
        updated_at: When ClinVar last updated the status, if it said.
        error_code: ClinVar's error code, if any: 1 if some records failed, 2 if all
            did.
        summary_report_url: Where to download the summary report, or "" until
            processing finishes.
        response: ClinVar's whole response.
    """

    status: str
    updated_at: datetime | None
    error_code: int | None
    summary_report_url: str
    response: dict[str, Any]


def _retry_after(response: requests.Response) -> int | None:
    """Returns the seconds in a response's Retry-After header, if it has a number."""
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else None


def _message(response: requests.Response) -> str:
    """Returns ClinVar's error message from a response, or its status code."""
    try:
        return response.json()["message"]
    except (ValueError, KeyError, TypeError):
        return f"HTTP {response.status_code}"


class ClinVarClient:
    """Makes the ClinVar Submission API calls the CSS needs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session: requests.Session | None = None,
    ) -> None:
        """Stores where ClinVar is and the key to send.

        Args:
            base_url: The API's base, such as CLINVAR_TEST_URL.
            api_key: The service account's API key.
            session: The requests session to send requests with.
        """
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._session = session or requests.Session()

    @classmethod
    def from_settings(cls) -> Self:
        """Builds a client from the CSS_ settings.

        Returns:
            A client for the configured ClinVar endpoint, or a simulated ClinVar when
            CSS_SIMULATE_CLINVAR is on.

        Raises:
            ImproperlyConfigured: If CSS_CLINVAR_API_KEY is empty.
        """
        if settings.CSS_SIMULATE_CLINVAR:
            # Imported here, since the simulator imports this module.
            from clinvar_submission_service.simulation import SimulatedClinVarClient  # ruff: ignore[import-outside-top-level] (It imports this module.)

            return SimulatedClinVarClient()  # ty: ignore[invalid-return-type] (It has the same methods.)
        if not settings.CSS_CLINVAR_API_KEY:
            error_message = "Set CSS_CLINVAR_API_KEY to talk to ClinVar."
            raise ImproperlyConfigured(error_message)
        return cls(
            base_url=settings.CSS_CLINVAR_API_URL,
            api_key=settings.CSS_CLINVAR_API_KEY,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        """Sends a request to ClinVar with the API key.

        Returns:
            ClinVar's response, which has a 2xx status.

        Raises:
            ClinVarError: If the request fails or ClinVar doesn't return a 2xx.
        """
        headers = {"SP-API-KEY": self._api_key, "Content-Type": "application/json"}
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=TIMEOUT,
            )
        except requests.RequestException as error:
            # The exception's text could include the request, so log only its type.
            message = f"Couldn't reach ClinVar ({type(error).__name__})."
            logger.warning("%s %s: %s", method, url, message)
            raise ClinVarError(message, retryable=True) from None
        if response.ok:
            return response
        retryable = response.status_code == 429 or response.status_code >= 500
        message = f"ClinVar returned {response.status_code}: {_message(response)}"
        logger.warning("%s %s: %s", method, url, message)
        raise ClinVarError(
            message, retryable=retryable, retry_after=_retry_after(response)
        )

    def submit(self, content: dict[str, Any], *, dry_run: bool = False) -> str | None:
        """Creates a submission in ClinVar.

        Args:
            content: The ClinVar submission content, which goes in an AddData action.
            dry_run: Whether to check only the format and the key, without creating a
                submission.

        Returns:
            The submission's ClinVar ID, such as SUB999999, or None for a dry run.

        Raises:
            ClinVarError: If ClinVar didn't accept the submission.
        """
        body = {
            "actions": [
                {"type": "AddData", "targetDb": "clinvar", "data": {"content": content}}
            ]
        }
        params = {"dry-run": "true"} if dry_run else {}
        response = self._request(
            "POST", f"{self.base_url}/submissions/", json=body, params=params
        )
        if response.status_code == 204:
            return None
        try:
            return response.json()["id"]
        except (ValueError, KeyError, TypeError):
            message = "ClinVar accepted the submission but returned no ID."
            raise ClinVarError(message, retryable=False) from None

    def get_status(self, clinvar_id: str) -> ClinVarStatus:
        """Reads a submission's status from ClinVar.

        Args:
            clinvar_id: The submission's ClinVar ID, such as SUB999999.

        Returns:
            ClinVar's status for the submission.

        Raises:
            ClinVarError: If the request fails or the response isn't a status.
        """
        url = f"{self.base_url}/submissions/{clinvar_id}/actions/"
        body = self._request("GET", url).json()
        try:
            action = body["actions"][0]
            status = action["status"]
        except (KeyError, IndexError, TypeError):
            message = "ClinVar's status response had no action."
            raise ClinVarError(message, retryable=True) from None
        responses = action.get("responses") or [{}]
        message = responses[0].get("message") or {}
        files = responses[0].get("files") or [{}]
        updated = action.get("updated")
        return ClinVarStatus(
            status=status,
            updated_at=datetime.fromisoformat(updated) if updated else None,
            error_code=message.get("errorCode"),
            summary_report_url=files[0].get("url", ""),
            response=body,
        )

    def get_summary_report(self, url: str) -> dict[str, Any]:
        """Downloads a submission's summary report from ClinVar.

        Args:
            url: The report's URL, from the submission's status.

        Returns:
            The summary report.
        """
        return self._request("GET", url).json()
