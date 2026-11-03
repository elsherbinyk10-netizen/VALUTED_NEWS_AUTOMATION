"""Conservative text-integrity checks and reversible UTF-8 mojibake repair."""
import re
from html import unescape

MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â\x80", "â\x81", "ï¿½", "�")


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



def final_article_integrity_issues(title, summary, body, seo_title="", seo_description_text=""):
    """Block publication when the finished article or SEO fields contain known text defects."""
    issues = []
    fields = (
        ("title", title),
        ("summary", summary),
        ("body", body),
        ("SEO title", seo_title),
        ("SEO description", seo_description_text),
    )
    for label, value in fields:
        for issue in text_integrity_issues("", "", value):
            issues.append(f"{label}:{issue}")
    if not str(title or "").strip():
        issues.append("missing_title")
    if not str(summary or "").strip():
        issues.append("missing_summary")
    if not str(body or "").strip():
        issues.append("missing_article_body")
    # JSON-LD descriptions are part of the rendered article and must pass too.
    for match in re.finditer(
        r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
        str(body or ""),
        re.I | re.S,
    ):
        try:
            import json
            data = json.loads(match.group(1))
        except (ValueError, TypeError):
            issues.append("body:invalid_json_ld")
            continue
        description = data.get("description", "") if isinstance(data, dict) else ""
        for issue in text_integrity_issues("", "", description):
            issues.append(f"JSON-LD description:{issue}")
    # Detect common publisher-snippet cutoffs at the end of a field. This is
    # deliberately conservative: only known incomplete word stems are blocked.
    terminal_fragments = {
        "challe", "challeng", "becaus", "governmen", "accordi", "whethe",
        "throug", "betwee", "anothe", "includ", "followin", "expecte",
        "announc", "reportin", "propos", "continu", "investigat",
        "developmen", "releas", "presiden", "ministe", "companie",
        "officia", "statemen", "emergen", "approache", "disruptio",
        "remai", "withou", "howeve", "althoug", "despit", "significan",
        "possibl", "severa", "percentag", "internationa",
    }
    for label, value in fields:
        plain = re.sub(r"<[^>]+>", " ", unescape(str(value or "")))
        tokens = re.findall(r"[A-Za-z]+", plain.lower())
        if tokens and tokens[-1] in terminal_fragments:
            issues.append(f"{label}:possible_mid_word_truncation")
    return sorted(set(issues))
