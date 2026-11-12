"""Defines the AS's API, version 1, served at /as/api/v1/.

Clients authenticate with an API key in the X-Api-Key header. Every active key can read
and change everything. The OpenAPI docs are at /as/api/v1/docs.
"""

import re

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.openapi.schema import OpenAPISchema

from affiliations_service.api.affiliations import router as affiliations_router
from affiliations_service.api.auth import ApiKeyAuth
from affiliations_service.api.cdwgs import router as cdwgs_router
from affiliations_service.api.memberships import router as memberships_router
from affiliations_service.api.users import router as users_router

# Ninja and pydantic make the docs' titles and summaries from Python names, so
# "gpm_uuid" becomes "Gpm Uuid". These words are fixed in every title and summary.
ACRONYMS = {
    "Id": "ID",
    "Ids": "IDs",
    "Gpm": "GPM",
    "Uuid": "UUID",
    "Cdwg": "CDWG",
    "Cdwgs": "CDWGs",
    "Orcid": "ORCID iD",
    "Clinvar": "ClinVar",
}
ACRONYM_PATTERN = re.compile(rf"\b({'|'.join(ACRONYMS)})\b")


def _fix_acronyms(node: object) -> None:
    """Fixes the acronyms in the titles and summaries of part of an OpenAPI schema."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"title", "summary"} and isinstance(value, str):
                node[key] = ACRONYM_PATTERN.sub(
                    lambda match: ACRONYMS[match.group()], value
                )
            else:
                _fix_acronyms(value)
    elif isinstance(node, list):
        for item in node:
            _fix_acronyms(item)


class AsNinjaAPI(NinjaAPI):
    """A NinjaAPI whose docs write acronyms such as ID and GPM in capitals."""

    def get_openapi_schema(
        self, *, path_prefix: str | None = None, path_params: dict | None = None
    ) -> OpenAPISchema:
        """Returns the OpenAPI schema with the acronyms in its labels fixed.

        Returns:
            The schema.
        """
        schema = super().get_openapi_schema(
            path_prefix=path_prefix, path_params=path_params
        )
        _fix_acronyms(schema)
        return schema


api = AsNinjaAPI(
    title="Affiliations Service API",
    version="1",
    description=(
        "The source of truth for ClinGen and non-ClinGen users and groups working in "
        "ClinGen apps."
    ),
    auth=ApiKeyAuth(),
    # The API is mounted inside the AS's URLconf, so its namespace is nested in as.
    urls_namespace="as:api-1",
)


@api.exception_handler(ValidationError)
def validation_error(request: HttpRequest, error: ValidationError) -> HttpResponse:
    """Turns a broken business rule into a 400 with a plain-language detail.

    Returns:
        A 400 response whose detail joins the error's messages.
    """
    return api.create_response(
        request, {"detail": " ".join(error.messages)}, status=400
    )


api.add_router("/affiliations", affiliations_router, tags=["Affiliations"])
api.add_router("/cdwgs", cdwgs_router, tags=["CDWGs"])
api.add_router("/memberships", memberships_router, tags=["Memberships"])
api.add_router("/users", users_router, tags=["Users"])
