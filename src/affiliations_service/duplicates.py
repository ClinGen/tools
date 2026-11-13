"""Finds users already in the AS who may be the same person as a new one.

Two real people can share a name, so a similar name is a warning that staff or a client
can override, unlike a taken email.
"""

import re
import unicodedata
from difflib import SequenceMatcher

from affiliations_service.models import User

# How alike two normalized names must be, from 0 to 1, to count as similar.
SIMILARITY_THRESHOLD = 0.85


def normalize(name: str) -> str:
    """Returns a name lowercased, without accents or punctuation, and single-spaced.

    Returns:
        The normalized name, such as "jose obrien" for "José O'Brien".
    """
    decomposed = unicodedata.normalize("NFKD", name)
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = re.sub(r"[^\w\s]", "", unaccented.lower()).split()
    return " ".join(words)


def similarity(a: str, b: str) -> float:
    """Returns how alike two normalized names are, from 0 to 1.

    The same names in another order, such as "smith jane" and "jane smith", count as
    equal.

    Returns:
        1 for equal names, 0 if either is blank, and difflib's ratio otherwise.
    """
    if not a or not b:
        return 0.0
    a_sorted = " ".join(sorted(a.split()))
    b_sorted = " ".join(sorted(b.split()))
    if a == b or a_sorted == b_sorted:
        return 1.0
    return max(
        SequenceMatcher(None, a, b).ratio(),
        SequenceMatcher(None, a_sorted, b_sorted).ratio(),
    )


def similar_users(name: str, *, preferred_name: str = "") -> list[User]:
    """Returns the users whose name or preferred name is like a new user's.

    Args:
        name: The new user's name.
        preferred_name: The new user's preferred name, if any.

    Returns:
        The similar users, most similar first, then by name.
    """
    new_names = [n for n in (normalize(name), normalize(preferred_name)) if n]
    if not new_names:
        return []
    scored = []
    for user in User.objects.all():
        old_names = [normalize(user.name), normalize(user.preferred_name)]
        score = max(similarity(new, old) for new in new_names for old in old_names)
        if score >= SIMILARITY_THRESHOLD:
            scored.append((score, user))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [user for _, user in scored]
