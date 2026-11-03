"""Conservative text-integrity checks and reversible UTF-8 mojibake repair."""
import re
from html import unescape

MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "ï¿½", "�")


def repair_mojibake(value):
    """Repair only strings that round-trip from Latin-1 bytes into valid UTF-8."""
    text = str(value or "")
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    # Require a clear reduction in known corruption markers; never guess at text.
    before = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    after = sum(repaired.count(marker) for marker in MOJIBAKE_MARKERS)
    return repaired if after < before else text


def text_integrity_issues(title, summary, body):
    """Return deterministic defects; avoid guessing whether a valid short word is a typo."""
    combined = unescape(" ".join((str(title or ""), str(summary or ""), str(body or ""))))
    issues = []
    if any(marker in combined for marker in MOJIBAKE_MARKERS):
        issues.append("possible_mojibake_or_replacement_character")
    if re.search(r"(?i)\b(?:challe|challeng|sent\s+of)\b", combined):
        issues.append("known_truncated_or_malformed_phrase")
    if re.search(r"(?i)\b(?:[a-z]{2,})(?:\uFFFD|\?{2,})\b", combined):
        issues.append("possible_missing_characters")
    return issues


def seo_description(summary, title, limit=155):
    """Build a readable SEO description, truncating only at a word boundary."""
    text = re.sub(r"\s+", " ", unescape(str(summary or title or ""))).strip()
    if len(text) <= limit:
        return text
    if limit < 5:
        return text[:limit]
    shortened = text[:limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[:limit - 3]).rstrip() + "..."
