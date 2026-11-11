"""Template tags for the CSS's pages."""

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def simulating_clinvar() -> bool:
    """Returns whether a simulated ClinVar is answering in place of ClinVar.

    Returns:
        The CSS_SIMULATE_CLINVAR setting, so the header can say so without each view
        passing it.
    """
    return settings.CSS_SIMULATE_CLINVAR
