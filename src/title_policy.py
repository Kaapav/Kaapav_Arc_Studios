"""Audience-first episode-title contract used before production packaging."""

from __future__ import annotations

import re


GENERIC_TITLES = {
    "the beginning", "the warning", "the secret", "the mystery", "the truth",
    "the choice", "the journey", "a new beginning", "the final battle",
}

STOP_WORDS = {
    "a", "an", "and", "at", "episode", "ep", "from", "his", "her", "him",
    "in", "of", "one", "the", "their", "them", "to", "was", "were", "with",
}

POLICY = (
    "Lead with a specific impossible event, urgent warning, moral choice, or personal consequence; "
    "use concrete story nouns and active stakes; keep branding and episode number at the end."
)


def display_title(title: str) -> str:
    return str(title or "").partition("|")[0].strip()


def validate_episode_title(title: str) -> list[str]:
    """Return fail-closed packaging issues for a proposed episode title."""
    display = display_title(title)
    words = re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", display)
    failures: list[str] = []
    if not display:
        return ["title is missing"]
    if display.casefold() in GENERIC_TITLES:
        failures.append("title is generic and does not state a story hook")
    if len(words) < 4:
        failures.append("audience-facing title needs at least four specific words")
    if len(words) > 14:
        failures.append("audience-facing title exceeds fourteen words")
    if len(display) < 24:
        failures.append("audience-facing title is too vague or short")
    if len(str(title)) > 90:
        failures.append("full title exceeds the channel title limit")
    if re.search(r"(?i)\bepisode\s*\d+\b", display):
        failures.append("episode numbering belongs at the end, not inside the hook")
    return failures


def title_opening_overlap(title: str, opening: str) -> dict[str, object]:
    """Prove the opening immediately pays off the audience-facing title."""
    title_terms = {
        word.casefold() for word in re.findall(r"[A-Za-z0-9]+", display_title(title))
        if len(word) >= 3 and word.casefold() not in STOP_WORDS
    }
    opening_terms = {
        word.casefold() for word in re.findall(r"[A-Za-z0-9]+", str(opening or ""))
        if len(word) >= 3
    }
    overlap = sorted(title_terms & opening_terms)
    return {
        "passed": bool(overlap), "matched_terms": overlap,
        "title_terms": sorted(title_terms),
    }
