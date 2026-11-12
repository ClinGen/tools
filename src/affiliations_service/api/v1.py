"""Defines the AS's API, version 1, served at /as/api/v1/.

Clients authenticate with an API key in the X-Api-Key header. Every active key can read
and change everything. The OpenAPI docs are at /as/api/v1/docs.
"""

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI

from affiliations_service.api.affiliations import router as affiliations_router
from affiliations_service.api.auth import ApiKeyAuth
from affiliations_service.api.cdwgs import router as cdwgs_router
from affiliations_service.api.memberships import router as memberships_router
from affiliations_service.api.people import router as people_router

api = NinjaAPI(
    title="Affiliations Service API",
    version="1",
    description=(
        "The source of truth for users and groups inside and outside of ClinGen apps."
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
api.add_router("/people", people_router, tags=["People"])
