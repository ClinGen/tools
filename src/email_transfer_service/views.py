from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from auth_.permissions import tool_permission_required
from email_transfer_service.clients import EtsClient
from email_transfer_service.forms import TransferForm
from email_transfer_service.transfers import check_preconditions

# What can go wrong while talking to AWS: missing settings, or a failed call.
AWS_ERRORS = (BotoCoreError, ClientError, ImproperlyConfigured)


@tool_permission_required("has_ets_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Shows the transfer form, and on submit, previews the transfer.

    The preview checks the preconditions and lists the steps a transfer would run,
    without changing anything.

    Returns:
        The home page, with the preview if the form was submitted and valid.
    """
    form = TransferForm(request.POST or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        try:
            preview = check_preconditions(
                EtsClient.from_settings(),
                form.cleaned_data["old_email"],
                form.cleaned_data["new_email"],
            )
        except AWS_ERRORS as error:
            messages.error(request, f"Couldn't check the preconditions: {error}")
    return render(
        request,
        "email_transfer_service/index.html",
        {"form": form, "preview": preview, "dry_run": settings.ETS_DRY_RUN},
    )
