import logging

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from auth_.permissions import tool_permission_required
from email_transfer_service.clients import EtsClient
from email_transfer_service.forms import TransferForm
from email_transfer_service.models import EmailTransfer
from email_transfer_service.transfers import check_preconditions, run_transfer

logger = logging.getLogger(__name__)

# What can go wrong while talking to AWS: missing settings, or a failed call.
AWS_ERRORS = (BotoCoreError, ClientError, ImproperlyConfigured)

LOOKUP_ERROR_MESSAGE = (
    "The ETS couldn't look up these emails. Try again in a few minutes, or ask a "
    "developer for help."
)


@tool_permission_required("has_ets_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Shows the transfer form, previews a transfer, and runs a confirmed one.

    The preview checks the preconditions and lists the steps a transfer would run,
    without changing anything. Confirming checks the preconditions again, since the
    data may have changed since the preview, and runs the transfer if they pass.

    Returns:
        The home page with the preview, or a redirect to a transfer that ran.
    """
    form = TransferForm(request.POST or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        try:
            client = EtsClient.from_settings()
            preview = check_preconditions(
                client,
                form.cleaned_data["old_email"],
                form.cleaned_data["new_email"],
            )
        except AWS_ERRORS:
            logger.exception("Couldn't check the preconditions.")
            messages.error(request, LOOKUP_ERROR_MESSAGE)
        else:
            if preview.plan and request.POST.get("confirm") == "true":
                transfer = run_transfer(
                    client,
                    preview.plan,
                    ran_by=request.user,  # type: ignore
                    dry_run=settings.ETS_DRY_RUN,
                )
                return redirect(transfer)
    return render(
        request,
        "email_transfer_service/index.html",
        {"form": form, "preview": preview, "dry_run": settings.ETS_DRY_RUN},
    )


@tool_permission_required("has_ets_permissions")
def transfer_list(request: HttpRequest) -> HttpResponse:
    """Lists past transfers, newest first.

    Returns:
        The list page.
    """
    transfers = EmailTransfer.objects.select_related("ran_by")
    return render(
        request,
        "email_transfer_service/list.html",
        {"transfers": transfers},
    )


@tool_permission_required("has_ets_permissions")
def transfer_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Shows a transfer and each step's result.

    Returns:
        The detail page.
    """
    transfer = get_object_or_404(EmailTransfer, slug=slug)
    return render(
        request,
        "email_transfer_service/detail.html",
        {"transfer": transfer},
    )
