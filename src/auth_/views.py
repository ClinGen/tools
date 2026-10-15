"""Houses views for the auth_ app."""

import logging

from clerk_backend_api import Clerk
from clerk_backend_api.security import VerifyTokenOptions, verify_token
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render

from auth_.models import UserProfile

logger = logging.getLogger(__name__)

clerk = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)


def login_(request: HttpRequest) -> HttpResponseRedirect | HttpResponse:
    """Renders Clerk's embedded sign-in widget.

    Returns:
        The login page, or a redirect to home if already logged in.
    """
    if request.user.is_authenticated:
        return redirect("home")
    logger.info("Login: rendering sign-in page")
    return render(
        request,
        "auth_/login.html",
        {"clerk_publishable_key": settings.CLERK_PUBLISHABLE_KEY},
    )


def callback(request: HttpRequest) -> HttpResponseRedirect | HttpResponse:
    """Verifies the Clerk session token, establishes a Django session, redirects home.

    Returns:
        A redirect to the home page on success, or to the login page on failure.
    """
    # When Clerk cannot deliver the session via a first-party __session cookie it falls
    # back to URL-based token delivery:
    #
    #   __clerk_db_jwt    — development instances / localhost. An opaque value that
    #                       Clerk.js exchanges for a real __session cookie.
    #   __clerk_handshake — production cross-domain (e.g. no satellite domain
    #                       configured). A signed token that Clerk.js exchanges with
    #                       the FAPI for a real __session cookie.
    #
    # In both cases we serve a minimal page that loads Clerk.js. Clerk.js detects
    # whichever parameter is present, performs the exchange, sets the cookie, and
    # redirects back here. On the second request the cookie is present and we fall
    # through to the verify path below.
    # These parameters take priority over any stale __session cookie that may be
    # lingering in the browser from a previous, now-expired session.
    param = (
        "__clerk_db_jwt"
        if request.GET.get("__clerk_db_jwt")
        else "__clerk_handshake"
        if request.GET.get("__clerk_handshake")
        else None
    )
    # In dev mode, Clerk may deliver __clerk_db_jwt as a cookie (not a URL parameter)
    # after an OAuth redirect. Serve the exchange page in this case too.
    if (
        not param
        and not any(k.startswith("__session") for k in request.COOKIES)
        and request.COOKIES.get("__clerk_db_jwt")
    ):
        param = "__clerk_db_jwt"
    if param:
        logger.info("Callback: token delivery via %s; serving exchange page", param)
        return render(
            request,
            "auth_/callback.html",
            {"clerk_publishable_key": settings.CLERK_PUBLISHABLE_KEY},
        )

    # Clerk sometimes appends a numeric suffix to the cookie name (e.g. __session.1),
    # so we scan by prefix rather than doing an exact lookup.
    session_cookies = {
        k: v for k, v in request.COOKIES.items() if k.startswith("__session")
    }
    logger.info("Callback: session cookies found: %s", list(session_cookies.keys()))
    token = next(iter(session_cookies.values()), None)
    if not token:
        logger.warning("Callback: no __session cookie; redirecting to login")
        return redirect("login")

    # Verify the session token using our secret key. Any exception means the token
    # is malformed, expired, or signed by a different Clerk instance.
    try:
        options = VerifyTokenOptions(secret_key=settings.CLERK_SECRET_KEY)
        payload = verify_token(token, options)
    except Exception:
        logger.exception("Callback: token verification failed")
        return redirect("login")

    # The verified payload carries the Clerk user ID in the `sub` claim, but not the
    # user's email. We fetch the full user record from the Clerk API to get it.
    clerk_user_id = payload["sub"]
    logger.info("Callback: token verified for Clerk user %s", clerk_user_id)

    try:
        clerk_user = clerk.users.get(user_id=clerk_user_id)
    except Exception:
        logger.exception("Callback: failed to fetch Clerk user %s", clerk_user_id)
        return redirect("login")

    # Locate the primary email address by matching primary_email_address_id against
    # the list of email objects on the Clerk user record.
    primary_email = next(
        (
            e.email_address
            for e in (clerk_user.email_addresses or [])
            if e.id == clerk_user.primary_email_address_id
        ),
        None,
    )
    if not primary_email:
        logger.warning("Callback: no primary email for Clerk user %s", clerk_user_id)
        return redirect("login")
    logger.info(
        "Callback: resolved email %s for Clerk user %s", primary_email, clerk_user_id
    )

    # Stash the Clerk session ID before calling login() so we can revoke it on logout.
    # login() flushes and recreates the Django session, so we write the ID afterward.
    clerk_session_id = payload.get("sid")

    user = authenticate(
        request,
        clerk_user_id=clerk_user_id,
        clerk_email=primary_email,
    )
    if user is None:
        logger.error(
            "Callback: authenticate() returned None for Clerk user %s", clerk_user_id
        )
        return redirect("login")

    login(request, user)
    if clerk_session_id:
        request.session["clerk_session_id"] = clerk_session_id
    logger.info(
        "Callback: logged in Django user %s (Clerk user %s)",
        user.get_username(),
        clerk_user_id,
    )
    return redirect("home")


def logout_(request: HttpRequest) -> HttpResponseRedirect:
    """Revokes the Clerk session server-side, clears the Django session, and redirects.

    Returns:
        A redirect to the login page.
    """
    sid = request.session.get("clerk_session_id")
    if sid:
        logger.info("Logout: revoking Clerk session %s", sid)
        try:
            clerk.sessions.revoke(session_id=sid)
            logger.info("Logout: Clerk session revoked")
        except Exception:
            logger.exception("Logout: failed to revoke Clerk session %s", sid)
    else:
        logger.info("Logout: no Clerk session ID in Django session")
    logout(request)
    return redirect("home")


def profile(request: HttpRequest) -> HttpResponse:
    """Returns the profile page for the user."""
    if request.user.is_authenticated:
        p, _ = UserProfile.objects.get_or_create(user=request.user)
        context = {"user_profile": p}
        return render(request, "auth_/profile.html", context)
    return redirect("login")
