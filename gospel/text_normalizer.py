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

# Cross-reference abbreviations ("cfr." = confronta/see/voir/…) that cause
# unwanted TTS pauses when the trailing dot is read as a sentence boundary.
CROSS_REF_EXPANSIONS: dict[str, dict[str, str]] = {
    "it": {"cfr": "confronta", "cf": "confronta"},
    "en": {"cfr": "see", "cf": "see"},
    "fr": {"cfr": "voir", "cf": "voir"},
    "es": {"cfr": "ver", "cf": "ver"},
    "pt": {"cfr": "ver", "cf": "ver"},
    "de": {"cfr": "vergleiche", "cf": "vergleiche", "vgl": "vergleiche"},
}

# Patterns to locate liturgy sections in each language feed.
# Keys: prima (1st reading), seconda (2nd reading), salmo (psalm – SKIPPED),
#       vangelo (gospel).
LITURGY_PATTERNS: dict[str, dict[str, str]] = {
    "it": {
        "prima":   r"^prima\s+lettura",
        "seconda": r"^seconda\s+lettura",
        "salmo":   r"^salmo\b",          # matches "Salmo Responsoriale"
        "vangelo": r"dal\s+vangelo|^vangelo\b",
    },
    "en": {
        "prima":   r"^a\s+reading\b|^first\s+reading",
        "seconda": r"^second\s+reading",
        "salmo":   r"^responsorial\s+psalm|^(the\s+)?psalm\b",
        "vangelo": r"^from\s+the\s+(holy\s+)?gospel|^holy\s+gospel",
    },
    "fr": {
        "prima":   r"^lecture\s+(du|de|d')",
        "seconda": r"^deuxi[eè]me\s+lecture",
        "salmo":   r"^psaume\b",
        "vangelo": r"^[eé]vangile\b",
    },
    "es": {
        "prima":   r"^lectura\s+de",
        "seconda": r"^segunda\s+lectura",
        "salmo":   r"^salmo\s+responsorial|^salmo\b",
        "vangelo": r"^lectura\s+del\s+(santo\s+)?evangelio|^evangelio\b",
    },
    "pt": {
        "prima":   r"^leitura\s+d",
        "seconda": r"^segunda\s+leitura",
        "salmo":   r"^salmo\s+responsorial|^salmo\b",
        "vangelo": r"^proclama[cç][aã]o\s+do\s+evangelho|^evangelho\b",
    },
    "de": {
        "prima":   r"^lesung\s+aus",
        "seconda": r"^zweite\s+lesung",
        "salmo":   r"^antwortpsalm|^psalm\b",
        "vangelo": r"^aus\s+dem\s+(heiligen\s+)?evangelium|^evangelium\b",
    },
}

# Introductory label for the pope's comment segment, per language.
# Tuple: (comment_word, pope_title)
POPE_COMMENT_LABELS: dict[str, tuple[str, str]] = {
    "it": ("Commento di", "Papa"),
    "en": ("Comment by", "Pope"),
    "fr": ("Commentaire de", "Pape"),
    "es": ("Comentario de", "Papa"),
    "pt": ("Comentário de", "Papa"),
    "de": ("Kommentar von", "Papst"),
}

# Word used to express a verse range ("1-13") in spoken form per language.
VERSE_RANGE_WORDS: dict[str, str] = {
    "it": "a",
    "en": "to",
    "fr": "à",
    "es": "a",
    "pt": "a",
    "de": "bis",
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


def _smooth_for_tts(text: str, language: str = "it", flatten_lines: bool = True) -> str:
    """Remove punctuation patterns that produce unwanted TTS pauses.

    - Strips the Italian responsorial-psalm marker ``R.``
    - Removes guillemet quotes « » (common in Italian/French liturgical text)
    - Replaces semicolons with __PAUSE__ marker (real silence inserted by audio generator)
    - Removes mid-sentence colons (introduces unnecessary pause)
    - Removes parentheses (reference wrappers cause brief pauses)
    - Removes dots that sit at a word boundary
    Applied to all languages.
    """
    if not text:
        return ""

    smoothed = text
    # Italian-specific: remove responsorial-psalm marker "R."
    # Use [ \t]* (not \s*) so trailing newlines are NOT consumed and
    # section boundaries in the multi-line text are preserved.
    if language == "it":
        smoothed = re.sub(r"\bR\.[ \t]*", "", smoothed)
    # Guillemet quotes — mark boundaries so the audio generator can apply a
    # different voice effect to quoted speech.  A comma before __QSTART__ gives
    # the natural breath pause before the quote begins; __QEND__ is silent.
    # Use [ \t]* (not \s*) to avoid consuming newlines and collapsing section
    # headers onto adjacent lines when flatten_lines=False.
    smoothed = re.sub(r"[ \t]*«[ \t]*", ", __QSTART__ ", smoothed)
    smoothed = re.sub(r"[ \t]*»[ \t]*", " __QEND__ ", smoothed)
    # Colons that are NOT at end of line/segment — replace with comma
    smoothed = re.sub(r":(?!\s*$)", ",", smoothed, flags=re.MULTILINE)
    # Parentheses — remove (they wrap references or metadata the reader trips over)
    smoothed = re.sub(r"[()]", "", smoothed)
    # Collapse consecutive commas (can result from colon before «, or other combos)
    smoothed = re.sub(r"(,\s*){2,}", ", ", smoothed)
    if flatten_lines:
        smoothed = re.sub(r"\s*\n\s*", " ", smoothed)
    else:
        smoothed = re.sub(r"\s*\n\s*", "\n", smoothed)
    # Remove dots that end a word/sentence to avoid TTS sentence-boundary pauses
    smoothed = re.sub(r"\.(?=\s|$)", "", smoothed)
    # Semicolons — replace with __PAUSE__ so the audio generator inserts real silence
    # Use [ \t]* (not \s*) to preserve newlines at line/section boundaries.
    smoothed = re.sub(r"[ \t]*;[ \t]*", " __PAUSE__ ", smoothed)
    # Collapse multiple horizontal spaces/tabs (NOT newlines — those are section
    # boundaries when flatten_lines=False and must be preserved).
    smoothed = re.sub(r"[ \t]{2,}", " ", smoothed)
    return smoothed.strip()


# Keep old name as an alias so any external callers are not broken.
def _smooth_italian_for_tts(text: str, flatten_lines: bool = True) -> str:
    return _smooth_for_tts(text, language="it", flatten_lines=flatten_lines)


def expand_cross_refs(text: str, language: str) -> str:
    """Expand cross-reference abbreviations like 'cfr.' so TTS reads them
    as a word rather than pausing on the trailing dot."""
    expansions = CROSS_REF_EXPANSIONS.get(language)
    if not expansions:
        return text
    for abbr, expansion in expansions.items():
        text = re.sub(
            rf"(?<![\w]){re.escape(abbr)}\.?(?![\w])",
            expansion,
            text,
            flags=re.IGNORECASE,
        )
    return text


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


def normalize_verse_refs(text: str, language: str) -> str:
    """Convert numeric verse references to natural spoken form.

    Handles:
    - ``5,1-13``  → ``5 1 a 13``
    - ``9,4b-10`` → ``9 4 a 10``  (sub-verse letter suffix stripped)
    - ``9 4b-10`` → ``9 4 a 10``  (same, already comma-less from feed)
    - ``5, 1``    → ``5 1``
    """
    range_word = VERSE_RANGE_WORDS.get(language, "to")

    # "9,4b-10" or "9, 4b-10" — sub-verse letter + range
    text = re.sub(
        r"(\d+),\s*(\d+)[a-z]\s*-\s*(\d+)",
        lambda m: f"{m.group(1)} {m.group(2)} {range_word} {m.group(3)}",
        text,
    )
    # "9 4b-10" — already comma-less (comes directly from feed), sub-verse + range
    text = re.sub(
        r"(\d+)\s+(\d+)[a-z]\s*-\s*(\d+)",
        lambda m: f"{m.group(1)} {m.group(2)} {range_word} {m.group(3)}",
        text,
    )
    # "5,1-13" or "5, 1-13" — plain range
    text = re.sub(
        r"(\d+),\s*(\d+)\s*-\s*(\d+)",
        lambda m: f"{m.group(1)} {m.group(2)} {range_word} {m.group(3)}",
        text,
    )
    # "5,1" or "5, 1" — simple chapter/verse without range
    text = re.sub(r"(\d+),\s*(\d+)", r"\1 \2", text)
    # Strip any remaining lone sub-verse letter (e.g. "4b" → "4")
    text = re.sub(r"\b(\d+)[a-z]\b", r"\1", text)
    return text


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
        # Expand cross-reference abbreviations (e.g. "cfr.") BEFORE Bible refs
        # so that any dot on the abbreviation is removed before TTS sees it.
        normalized = expand_cross_refs(normalized, language)
        normalized = expand_bible_refs(normalized, language)
        # Convert verse refs like "5, 1-13" → "5 1 a 13" to remove pause-causing comma
        normalized = normalize_verse_refs(normalized, language)
        # Remove punctuation patterns that cause unwanted pauses for all languages
        normalized = _smooth_for_tts(normalized, language=language, flatten_lines=flatten_lines)

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

    # Multi-language pope name / title detection
    if re.search(
        r"francesco|francis|fran[cç]ois|francisco|franziskus"
        r"|benedetto|benedict|benedikt"
        r"|giovanni\s+paolo|john\s+paul|jean\s+paul|juan\s+pablo|jo[aã]o\s+paulo|johannes\s+paul"
        r"|paolo\s+vi|paul\s+vi|pablo\s+vi|paulo\s+vi"
        r"|papa|pope|pape|papst",
        meta,
        re.IGNORECASE,
    ):
        return content, meta

    return stripped, None


def build_liturgy_segments(description: str, lang: str = "it") -> list[str]:
    """Split a liturgy description into spoken segments, skipping the psalm.

    Sections detected per language (prima lettura, optional seconda lettura,
    salmo – skipped entirely, vangelo, optional pope comment).
    Returns a list of normalised text strings to be read aloud with silence
    inserted between them by the audio generator.
    If no structure is detected the full text is returned as a single segment.
    """
    text = normalize_for_tts(description, lang=lang, flatten_lines=False)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [text]

    patterns = LITURGY_PATTERNS.get(lang)
    if not patterns:
        return [text]

    def find(key: str) -> int:
        return _find_line_index(lines, patterns[key])

    idx_prima   = find("prima")
    idx_seconda = find("seconda")
    idx_salmo   = find("salmo")
    idx_vangelo = find("vangelo")

    last_line = lines[-1]
    comment_content, comment_meta = _extract_pope_meta(last_line)
    has_comment = comment_meta is not None and idx_vangelo != -1

    if idx_prima == -1 or idx_vangelo == -1:
        return [text]

    segments: list[str] = []

    # --- First reading ---
    if idx_seconda != -1 and idx_seconda > idx_prima:
        prima_end = idx_seconda
    elif idx_salmo != -1 and idx_salmo > idx_prima:
        prima_end = idx_salmo
    else:
        prima_end = idx_vangelo
    prima_section = "\n".join(lines[idx_prima:prima_end]).strip()
    if prima_section:
        segments.append(prima_section)

    # --- Second reading (optional) ---
    if idx_seconda != -1 and idx_seconda > idx_prima:
        if idx_salmo != -1 and idx_salmo > idx_seconda:
            seconda_end = idx_salmo
        else:
            seconda_end = idx_vangelo
        seconda_section = "\n".join(lines[idx_seconda:seconda_end]).strip()
        if seconda_section:
            segments.append(seconda_section)

    # --- Psalm is SKIPPED entirely ---

    # --- Gospel ---
    vangelo_end = len(lines) - 1 if has_comment else len(lines)
    vangelo_section = "\n".join(lines[idx_vangelo:vangelo_end]).strip()
    # For Italian feeds narrow to the actual gospel text after the header line
    if lang == "it":
        vangelo_match = re.search(r"dal\s+vangelo.*", vangelo_section, re.IGNORECASE | re.DOTALL)
        if vangelo_match:
            vangelo_section = vangelo_match.group(0).strip()
    if vangelo_section:
        segments.append(vangelo_section)

    # --- Pope's comment ---
    if has_comment:
        comment_word, pope_title = POPE_COMMENT_LABELS.get(lang, POPE_COMMENT_LABELS["it"])
        pope_intro = comment_meta.replace(" - ", ", ")
        if not re.search(r"\b(papa|pope|pape|papst)\b", pope_intro, re.IGNORECASE):
            pope_intro = f"{pope_title} {pope_intro}"
        comment_section = f"{comment_word} {pope_intro}."
        if comment_content:
            comment_section = f"{comment_section}\n{comment_content}"
        segments.append(comment_section)

    return segments if segments else [text]


# Backward-compatible alias
def build_italian_liturgy_segments(description: str) -> list[str]:
    return build_liturgy_segments(description, lang="it")
