"""Conservative text-integrity checks and reversible UTF-8 mojibake repair."""
import re
from html import unescape

MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â\\x80", "â\\x81", "ï¿½", "�")
# UTF-8 bytes that were decoded as Latin-1/Windows-1252. Repair only complete
# byte sequences; leave standalone accented letters and ambiguous fragments alone.
_CORRUPT_UTF8 = re.compile(
    r"(?:Ã[\\x80-\\xBF]|Â[\\x80-\\xBF]|â[\\x80-\\xBF]{1,2})"
)


def _repair_utf8_sequences(value):
    def decode_match(match):
        candidate = match.group(0)
        try:
            decoded = bytes(ord(char) for char in candidate).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError, ValueError):
            return candidate
        return decoded

    return _CORRUPT_UTF8.sub(decode_match, value)


def repair_mojibake(value):
    """Repair complete reversible UTF-8-as-Latin-1 sequences, including mixed Unicode."""
    text = str(value or "")
    # Repeated passes handle double-encoded text (e.g. ÃƒÂ© -> é).
    for _ in range(3):
        repaired = _repair_utf8_sequences(text)
        if repaired == text:
            break
        text = repaired
    return text


def text_integrity_issues(title, summary, body):
    """Flag actual malformed UTF-8 byte sequences and replacement characters."""
    combined = unescape(" ".join((str(title or ""), str(summary or ""), str(body or ""))))
    issues = []
    if _CORRUPT_UTF8.search(combined) or "�" in combined or "ï¿½" in combined:
        issues.append("possible_mojibake_or_replacement_character")
    if re.search(r"(?i)\\b(?:challe|challeng|sent\\s+of)\\b", combined):
        issues.append("known_truncated_or_malformed_phrase")
    if re.search(r"(?i)\\b(?:[a-z]{2,})(?:\\uFFFD|\\?{2,})\\b", combined):
        issues.append("possible_missing_characters")
    return issues

def normalize_article_summary(summary, title="", limit=240):
    """Keep article excerpts readable: never end on a clipped word or sentence fragment."""
    text = re.sub(r"\s+", " ", unescape(str(summary or title or ""))).strip()
    if len(text) <= limit:
        return text
    prefix = text[:limit + 1]
    sentence_ends = list(re.finditer(r"""[.!?]["'”’)]*(?=\s|$)""", prefix))
    usable = [match.end() for match in sentence_ends if match.end() >= max(70, int(limit * 0.35))]
    if usable:
        return text[:usable[-1]].strip()
    shortened = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[:limit - 1].rstrip()) + "…"


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
