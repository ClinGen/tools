"""Lists the tools that ClinGen Tools houses."""

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class Tool:
    """A tool listed on the landing page.

    Attributes:
        name: The tool's full name.
        abbreviation: The tool's abbreviation, which is also its URL prefix.
        namespace: The URL namespace of the tool's URLconf.
        description: A one-sentence description of what the tool does.
        home: The name, in the tool's namespace, of the page the landing page links to.
    """

    name: str
    abbreviation: str
    namespace: str
    description: str
    home: str = "index"

    def url(self) -> str | None:
        """Returns the URL of the tool's home page, or None if it isn't mounted."""
        try:
            return reverse(f"{self.namespace}:{self.home}")
        except NoReverseMatch:
            return None


TOOLS = [
    Tool(
        name="Affiliations Service",
        abbreviation="AS",
        namespace="as",
        description=(
            "The source of truth for ClinGen affiliations (expert panels and working "
            "groups)."
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
    ),
]


def mounted_tools() -> list[tuple[Tool, str]]:
    """Returns each tool whose URLconf is mounted, with its home page's URL."""
    return [(tool, url) for tool in TOOLS if (url := tool.url())]


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
