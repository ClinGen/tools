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
    """

    name: str
    abbreviation: str
    namespace: str
    description: str

    def url(self) -> str | None:
        """Returns the URL of the tool's index page, or None if it isn't mounted."""
        try:
            return reverse(f"{self.namespace}:index")
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
    ),
    Tool(
        name="Email Transfer Service",
        abbreviation="ETS",
        namespace="ets",
        description=(
            "Moves a Gene Curation Interface or Variant Curation Interface user's "
            "account from an old email to a new one."
        ),
    ),
]


def mounted_tools() -> list[tuple[Tool, str]]:
    """Returns each tool whose URLconf is mounted, with its index URL."""
    return [(tool, url) for tool in TOOLS if (url := tool.url())]
