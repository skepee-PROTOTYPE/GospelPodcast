import html
import re
from typing import Optional

LANGUAGE_BIBLE_EXPANSIONS = {
    "it": {
        "mt": "Matteo",
        "mc": "Marco",
        "lc": "Luca",
        "gv": "Giovanni",
        "at": "Atti degli Apostoli",
        "rm": "Lettera ai Romani",
        "1cor": "Prima lettera ai Corinzi",
        "2cor": "Seconda lettera ai Corinzi",
        "gal": "Lettera ai Galati",
        "ef": "Lettera agli Efesini",
        "fil": "Lettera ai Filippesi",
        "col": "Lettera ai Colossesi",
        "1ts": "Prima lettera ai Tessalonicesi",
        "2ts": "Seconda lettera ai Tessalonicesi",
        "1tm": "Prima lettera a Timoteo",
        "2tm": "Seconda lettera a Timoteo",
        "tt": "Lettera a Tito",
        "fm": "Lettera a Filemone",
        "eb": "Lettera agli Ebrei",
        "gc": "Lettera di Giacomo",
        "1pt": "Prima lettera di Pietro",
        "2pt": "Seconda lettera di Pietro",
        "1gv": "Prima lettera di Giovanni",
        "2gv": "Seconda lettera di Giovanni",
        "3gv": "Terza lettera di Giovanni",
        "gd": "Lettera di Giuda",
        "ap": "Apocalisse",
        "sir": "Siràcide",
        "sap": "Sapienza",
        "qo": "Qoelet",
        "ct": "Cantico dei Cantici",
        "is": "Isaia",
        "ger": "Geremia",
        "lam": "Lamentazioni",
        "bar": "Baruc",
        "ez": "Ezechiele",
        "dn": "Daniele",
        "os": "Osea",
        "gl": "Gioele",
        "am": "Amos",
        "ab": "Abacuc",
        "sof": "Sofonia",
        "ag": "Aggeo",
        "zc": "Zaccaria",
        "ml": "Malachia",
        "sal": "Salmo",
    },
    "en": {
        "mt": "Matthew",
        "mk": "Mark",
        "lk": "Luke",
        "jn": "John",
        "acts": "Acts",
        "rom": "Romans",
        "1cor": "First Corinthians",
        "2cor": "Second Corinthians",
        "1thes": "First Thessalonians",
        "2thes": "Second Thessalonians",
        "1tim": "First Timothy",
        "2tim": "Second Timothy",
        "heb": "Hebrews",
        "jas": "James",
        "1pet": "First Peter",
        "2pet": "Second Peter",
        "1jn": "First John",
        "2jn": "Second John",
        "3jn": "Third John",
        "rev": "Revelation",
        "ps": "Psalm",
        "sir": "Sirach",
    },
    "es": {
        "mt": "Mateo",
        "mc": "Marcos",
        "lc": "Lucas",
        "jn": "Juan",
        "hch": "Hechos",
        "rm": "Romanos",
        "1cor": "Primera carta a los Corintios",
        "2cor": "Segunda carta a los Corintios",
        "ap": "Apocalipsis",
        "sal": "Salmo",
        "sir": "Eclesiástico",
    },
    "fr": {
        "mt": "Matthieu",
        "mc": "Marc",
        "lc": "Luc",
        "jn": "Jean",
        "rm": "Lettre aux Romains",
        "1cor": "Première lettre aux Corinthiens",
        "2cor": "Deuxième lettre aux Corinthiens",
        "ap": "Apocalypse",
        "ps": "Psaume",
        "sir": "Siracide",
    },
    "pt": {
        "mt": "Mateus",
        "mc": "Marcos",
        "lc": "Lucas",
        "jo": "João",
        "at": "Atos dos Apóstolos",
        "rm": "Romanos",
        "1cor": "Primeira carta aos Coríntios",
        "2cor": "Segunda carta aos Coríntios",
        "ap": "Apocalipse",
        "sl": "Salmo",
        "sir": "Eclesiástico",
    },
    "de": {
        "mt": "Matthäus",
        "mk": "Markus",
        "lk": "Lukas",
        "joh": "Johannes",
        "röm": "Römer",
        "1kor": "Erster Korintherbrief",
        "2kor": "Zweiter Korintherbrief",
        "offb": "Offenbarung",
        "ps": "Psalm",
        "sir": "Jesus Sirach",
    },
}


def _canonical_ref_token(token: str) -> str:
    return re.sub(r"[\.\s]", "", (token or "")).lower()


def _build_abbrev_pattern(expansions: dict[str, str]) -> re.Pattern[str]:
    parts = []
    for key in sorted(expansions.keys(), key=len, reverse=True):
        if key and key[0].isdigit():
            parts.append(re.escape(key[0]) + r"\s*" + re.escape(key[1:]))
        else:
            parts.append(re.escape(key))
    return re.compile(rf"(?<!\w)({'|'.join(parts)})\.?(?!\w)", re.IGNORECASE)


ABBREV_PATTERNS = {
    language: _build_abbrev_pattern(expansions)
    for language, expansions in LANGUAGE_BIBLE_EXPANSIONS.items()
}


def _detect_lang(lang: Optional[str], feed_url: Optional[str]) -> Optional[str]:
    lang_value = (lang or "").strip().lower()
    if lang_value in LANGUAGE_BIBLE_EXPANSIONS:
        return lang_value

    url = (feed_url or "").lower()
    for code in LANGUAGE_BIBLE_EXPANSIONS:
        if f"/{code}/" in url:
            return code

    return None


def decode_html_entities(value: str) -> str:
    if not value:
        return ""
    decoded = value
    for _ in range(3):
        newer = html.unescape(decoded)
        if newer == decoded:
            break
        decoded = newer
    return decoded.replace("\xa0", " ")


def html_to_plain_text(value: str) -> str:
    if not value:
        return ""

    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<li\b[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = decode_html_entities(text)

    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_punctuation_for_tts(text: str, flatten_lines: bool = True) -> str:
    if not text:
        return ""

    normalized = text

    normalized = re.sub(r"\s+([,;:.!?])", r"\1", normalized)
    normalized = re.sub(r"([,;:.!?])(?!\s|$)", r"\1 ", normalized)

    normalized = re.sub(r"(?:,\s*){2,}", ", ", normalized)
    normalized = re.sub(r";\s*;{1,}", "; ", normalized)
    normalized = re.sub(r":\s*:{1,}", ": ", normalized)
    normalized = re.sub(r"!\s*!{1,}", "! ", normalized)
    normalized = re.sub(r"\?\s*\?{1,}", "? ", normalized)

    if flatten_lines:
        normalized = re.sub(r"\s*\n\s*", " ", normalized)
    else:
        normalized = re.sub(r"\s*\n\s*", "\n", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized.strip()


def _smooth_italian_for_tts(text: str, flatten_lines: bool = True) -> str:
    if not text:
        return ""

    smoothed = text
    smoothed = re.sub(r"\bR\.\s*", "", smoothed)
    if flatten_lines:
        smoothed = re.sub(r"\s*\n\s*", " ", smoothed)
    else:
        smoothed = re.sub(r"\s*\n\s*", "\n", smoothed)
    smoothed = re.sub(r"\.(?=\s|$)", "", smoothed)
    smoothed = re.sub(r"\s{2,}", " ", smoothed)
    return smoothed.strip()


def expand_bible_refs(text: str, language: str) -> str:
    if not text:
        return ""

    expansions = LANGUAGE_BIBLE_EXPANSIONS.get(language)
    pattern = ABBREV_PATTERNS.get(language)
    if not expansions or not pattern:
        return text

    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        canonical = _canonical_ref_token(token)
        return expansions.get(canonical, token)

    return pattern.sub(repl, text)


def normalize_for_tts(
    text: str,
    lang: Optional[str] = None,
    feed_url: Optional[str] = None,
    flatten_lines: bool = True,
) -> str:
    normalized = html_to_plain_text(text)
    normalized = normalize_punctuation_for_tts(normalized, flatten_lines=flatten_lines)

    language = _detect_lang(lang, feed_url)
    if language:
        normalized = expand_bible_refs(normalized, language)
    if language == "it":
        normalized = _smooth_italian_for_tts(normalized, flatten_lines=flatten_lines)

    return normalized


def _find_line_index(lines: list[str], pattern: str) -> int:
    rx = re.compile(pattern, re.IGNORECASE)
    for idx, line in enumerate(lines):
        if rx.search(line.strip()):
            return idx
    return -1


def _extract_pope_meta(line: str) -> tuple[str, Optional[str]]:
    stripped = line.strip()
    match = re.search(r"\(([^()]+)\)\s*$", stripped)
    if not match:
        return stripped, None

    meta = match.group(1).strip()
    content = stripped[:match.start()].strip()
    if not content:
        content = stripped

    if re.search(r"francesco|benedetto|giovanni\s+paolo|paolo\s+vi|papa", meta, re.IGNORECASE):
        return content, meta

    return stripped, None


def build_italian_liturgy_segments(description: str) -> list[str]:
    text = normalize_for_tts(description, lang="it", flatten_lines=False)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [text]

    idx_prima = _find_line_index(lines, r"^prima\s+lettura")
    idx_salmo = _find_line_index(lines, r"^salmo\s+responsoriale")
    idx_vangelo = _find_line_index(lines, r"dal\s+vangelo|^vangelo")

    last_line = lines[-1]
    comment_content, comment_meta = _extract_pope_meta(last_line)
    has_comment = comment_meta is not None and idx_vangelo != -1

    if idx_prima == -1 or idx_vangelo == -1:
        return [text]

    prima_end = idx_salmo if idx_salmo != -1 and idx_salmo > idx_prima else idx_vangelo
    prima_section = "\n".join(lines[idx_prima:prima_end]).strip()

    vangelo_end = len(lines)
    if has_comment:
        vangelo_end = len(lines) - 1
    vangelo_section = "\n".join(lines[idx_vangelo:vangelo_end]).strip()
    vangelo_match = re.search(r"dal\s+vangelo.*", vangelo_section, re.IGNORECASE | re.DOTALL)
    if vangelo_match:
        vangelo_section = vangelo_match.group(0).strip()

    segments = []
    if prima_section:
        segments.append(prima_section)
    if vangelo_section:
        segments.append(vangelo_section)

    if has_comment:
        pope_intro = comment_meta.replace(" - ", ", ")
        if not re.search(r"\bpapa\b", pope_intro, re.IGNORECASE):
            pope_intro = f"Papa {pope_intro}"
        comment_section = f"Commento di {pope_intro}."
        if comment_content:
            comment_section = f"{comment_section}\n{comment_content}"
        segments.append(comment_section)

    return segments if segments else [text]
