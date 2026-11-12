"""Builds the breadcrumb trails at the top of each tool's pages, like the HCI's.

Each view passes its trail to its template as `breadcrumbs`, a list of crumbs that
starts at a section's list page and ends at the current page, and the template
includes `common/breadcrumbs.html`. Unlike the HCI's, the trails don't start with Home,
since the site navbar already links to the ClinGen Tools home page.
"""

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


def section(
    text: str, url_name: str, icon: str = "search", *, current: bool = False
) -> Crumb:
    """Returns the crumb for a section's list page, such as Affiliation Search.

    Args:
        text: What the crumb says.
        url_name: The list page's URL name, such as "as:index".
        icon: The Bootstrap icon to show before the text.
        current: Whether the list page is the current page.

    Returns:
        The crumb.
    """
    return Crumb(text, "" if current else reverse(url_name), icon)


def detail(obj: object, *, current: bool = False) -> Crumb:
    """Returns the crumb for an object's page, named after the object."""
    return Crumb(str(obj), "" if current else obj.get_absolute_url(), "journal-text")  # ty: ignore[unresolved-attribute] (Only called with models that have pages.)


def action(text: str, icon: str) -> Crumb:
    """Returns the crumb for a current page such as Edit, New Batch, or Settings."""
    return Crumb(text, "", icon)
