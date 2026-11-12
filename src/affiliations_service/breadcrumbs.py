"""Builds the breadcrumb trails at the top of the AS's pages, like the HCI's."""

from dataclasses import dataclass

from django.urls import reverse


@dataclass(frozen=True)
class Crumb:
    """One step in a breadcrumb trail.

    Attributes:
        text: What the crumb says.
        url: Where it links, or "" for the current page.
        icon: The Bootstrap icon to show before the text.
    """

    text: str
    url: str
    icon: str


def trail(*crumbs: Crumb) -> list[Crumb]:
    """Returns a trail that starts at the ClinGen Tools home page.

    Args:
        *crumbs: The crumbs after Home. The last one is the current page.

    Returns:
        Home, then the given crumbs.
    """
    return [Crumb("Home", reverse("home"), "house"), *crumbs]


def search(text: str, url_name: str, *, current: bool = False) -> Crumb:
    """Returns the crumb for a list page, such as Affiliation Search."""
    return Crumb(text, "" if current else reverse(url_name), "search")


def detail(obj: object, *, current: bool = False) -> Crumb:
    """Returns the crumb for an object's page."""
    return Crumb(str(obj), "" if current else obj.get_absolute_url(), "journal-text")  # ty: ignore[unresolved-attribute] (Only called with models that have pages.)


def action(text: str, icon: str) -> Crumb:
    """Returns the crumb for a page that acts on an object, such as Edit."""
    return Crumb(text, "", icon)
