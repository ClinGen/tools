"""Lists the tools that ClinGen Tools houses."""

from dataclasses import dataclass

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from auth_.permissions import has_tool_permission


@dataclass(frozen=True)
class Tool:
    """A tool listed on the landing page.

    Attributes:
        name: The tool's full name.
        abbreviation: The tool's abbreviation, which is also its URL prefix.
        namespace: The URL namespace of the tool's URLconf.
        description: A one-sentence description of what the tool does.
        home: The name, in the tool's namespace, of the page the landing page links to.
        permission: The `UserProfile` flag a person needs to see the tool, or "" if
            everyone sees it.
    """

    name: str
    abbreviation: str
    namespace: str
    description: str
    home: str = "index"
    permission: str = ""

    def url(self) -> str | None:
        """Returns the URL of the tool's home page, or None if it isn't mounted."""
        try:
            return reverse(f"{self.namespace}:{self.home}")
        except NoReverseMatch:
            return None

    def is_visible_to(self, request: HttpRequest) -> bool:
        """Reports whether the request's user may see the tool.

        Returns:
            True if the tool needs no permission or the user has it.
        """
        return not self.permission or has_tool_permission(request, self.permission)


TOOLS = [
    Tool(
        name="Affiliations Service",
        abbreviation="AS",
        namespace="as",
        description=(
            "The source of truth for ClinGen and non-ClinGen users and groups working "
            "in ClinGen apps."
        ),
    ),
    Tool(
        name="ClinVar Submission Service",
        abbreviation="CSS",
        namespace="css",
        description=(
            "Forwards ClinVar submissions from ClinGen clients to ClinVar and tracks "
            "each one until ClinVar has processed it."
        ),
        home="records",
    ),
    Tool(
        name="Email Transfer Service",
        abbreviation="ETS",
        namespace="ets",
        description="Moves a GCI/VCI user's account from an old email to a new one.",
        permission="has_ets_permissions",
    ),
]


def visible_tools(request: HttpRequest) -> list[tuple[Tool, str]]:
    """Returns each mounted tool the request's user may see, with its home page URL."""
    return [
        (tool, url)
        for tool in TOOLS
        if tool.is_visible_to(request) and (url := tool.url())
    ]


def get_tool(namespace: str) -> Tool:
    """Returns the tool with the given URL namespace.

    Raises:
        LookupError: If no tool has that namespace.
    """
    for tool in TOOLS:
        if tool.namespace == namespace:
            return tool
    error_message = f"No tool has the namespace {namespace!r}."
    raise LookupError(error_message)
