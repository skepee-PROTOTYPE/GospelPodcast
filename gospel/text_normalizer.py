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
        "vangelo": r"^dal\s+vangelo|^vangelo\b",  # ^ anchors prevent false match inside body text
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

# Phrases that mark the end of the gospel reading and the start of the pope comment.
# Used for flat-text feeds that have no newlines between sections.
GOSPEL_CLOSING_PATTERNS: dict[str, str] = {
    "it": r"parola\s+del\s+(vangelo|signore)\b",
    "en": r"(the\s+)?gospel\s+of\s+the\s+lord\b",
    "fr": r"parole\s+du\s+seigneur\b",
    "es": r"palabra\s+del\s+se[ñn]or\b",
    "pt": r"palavra\s+d[ao]\s+salva[cç][aã]o\b|palavra\s+do\s+senhor\b",
    "de": r"wort\s+des\s+herrn\b",
}

# Opening phrases that typically begin a pope comment/reflection block.
# Used as a secondary heuristic when the gospel closing phrase is absent.
POPE_COMMENT_INTRO_PATTERNS: dict[str, str] = {
    "it": r"\bfratelli\s+e\s+sorelle\b|\bcari\s+amici\b",
    "en": r"\bdear\s+brothers\s+and\s+sisters\b",
    "fr": r"\bchers\s+fr[eè]res\s+et\s+s[oœ]urs\b",
    "es": r"\bqueridos\s+hermanos\s+y\s+hermanas\b",
    "pt": r"\birm[aã]os\s+e\s+irm[aã]s\b|\bcaros\s+irm[aã]os\b",
    "de": r"\bliebe\s+br[üu]der\s+und\s+schwestern\b",
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
    - Converts trailing-apostrophe accent notation (Gesu' → Gesù, cosi' → così)
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
    # Convert apostrophe-accent notation to proper Unicode accented chars.
    # Pattern: vowel followed by ' at word-end (before space/punct/end).
    # Italian, French and Portuguese all use this convention in some sources.
    # Defaults to grave accent (the most common in liturgical Italian);
    # e stays as è which is fine for stress marking purposes.
    if language in ("it", "fr", "pt"):
        _GRAVE = str.maketrans("aeiouAEIOU", "àèìòùÀÈÌÒÙ")
        def _to_accent(m: re.Match) -> str:  # noqa: E306
            return m.group(1).translate(_GRAVE)
        smoothed = re.sub(
            r"([aeiouAEIOU])'(?=[\s,;:.!?\"\[\]]|$)",
            _to_accent,
            smoothed,
            flags=re.MULTILINE,
        )
    # Guillemet quotes « » AND straight double quotes " " — mark boundaries so
    # the audio generator applies a different pitch/rate to quoted speech.
    # A brief pause before __QSTART__ lets the listener hear the transition.
    # Use [ \t]* (not \s*) to avoid consuming newlines and collapsing section
    # headers onto adjacent lines when flatten_lines=False.
    smoothed = re.sub(r"[ \t]*«[ \t]*", " __QSTART__ ", smoothed)
    smoothed = re.sub(r"[ \t]*»[ \t]*", " __QEND__ ", smoothed)
    # Straight double-quotes (Unicode " " and ASCII ") used for direct speech.
    # Open quote → __QSTART__, closing quote → __QEND__.
    # We treat an opening quote as one that follows whitespace / start-of-line
    # or a punctuation marker, and a closing quote as one that precedes
    # whitespace, punctuation or end-of-line.
    smoothed = re.sub(r"\u201c", " __QSTART__ ", smoothed)   # U+201C "
    smoothed = re.sub(r"\u201d", " __QEND__ ", smoothed)     # U+201D "
    # ASCII double-quote heuristic: use sentence context.
    # Opening: at start of string/line, OR after space/newline/punctuation
    smoothed = re.sub(r'^"(?=\S)', "__QSTART__ ", smoothed, flags=re.MULTILINE)
    smoothed = re.sub(r'(?<=[\s,\-])"(?=\S)', " __QSTART__ ", smoothed)
    # Closing: before whitespace/punctuation/EOL, after any character (incl. space)
    # This covers: `."`, `. "`, and `"` at end of line.
    smoothed = re.sub(r'"(?=\s*(?:[,;:.!?]|\s|$))', " __QEND__ ", smoothed, flags=re.MULTILINE)
    # Colons that are NOT at end of line/segment — replace with comma
    smoothed = re.sub(r":(?!\s*$)", ",", smoothed, flags=re.MULTILINE)
    # Parentheses — remove (they wrap references or metadata the reader trips over)
    smoothed = re.sub(r"[()]", "", smoothed)
    # Space-dash-space used as em-dash in Italian liturgical text (e.g. "disse - rispose")
    # → replace with comma so TTS reads a natural pause instead of "trattino"
    smoothed = re.sub(r"[ \t]+-[ \t]+", ", ", smoothed)
    # Collapse consecutive commas (can result from colon before «, or other combos)
    smoothed = re.sub(r"(,\s*){2,}", ", ", smoothed)
    if flatten_lines:
        smoothed = re.sub(r"\s*\n\s*", " ", smoothed)
    else:
        smoothed = re.sub(r"\s*\n\s*", "\n", smoothed)
    # NOTE: periods are intentionally kept — Cloud TTS Neural2 uses them for natural
    # sentence-boundary pauses. Explicit <break> tags are added in _escape_and_mark.
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

    # Multi-language pope name / title detection
    if re.search(
        r"francesco|francis|fran[cç]ois|francisco|franziskus"
        r"|benedetto|benoît|benoit|benedict|benedikt"
        r"|giovanni\s+paolo|john\s+paul|jean\s+paul|juan\s+pablo|jo[aã]o\s+paulo|johannes\s+paul"
        r"|paolo\s+vi|paul\s+vi|pablo\s+vi|paulo\s+vi"
        r"|papa|pope|pape|papst",
        meta,
        re.IGNORECASE,
    ):
        # Return only the body text (may be empty when the line is the attribution alone)
        return content, meta

    return stripped, None


_POPE_NAME_RE = re.compile(
    r"francesco|francis|fran[cç]ois|francisco|franziskus"
    r"|benedetto|benoît|benoit|benedict|benedikt"
    r"|giovanni\s+paolo|john\s+paul|jean\s+paul|juan\s+pablo|jo[aã]o\s+paulo|johannes\s+paul"
    r"|paolo\s+vi|paul\s+vi|pablo\s+vi|paulo\s+vi"
    r"|papa\b|pope\b|pape\b|papst\b",
    re.IGNORECASE,
)


def _find_pope_attribution_in_lines(lines: list[str]) -> tuple[Optional[str], Optional[int]]:
    """Scan all non-empty lines for a pope attribution in either format:

    Format A: a line ending with ``(Pope Name, Event Date)``
    Format B: a standalone line that IS just "Pope Name - Event, Date" with no
              sentence content other than the attribution.

    Returns ``(meta_string, line_index)`` or ``(None, None)`` if not found.
    The caller should use ``line_index`` to split body vs. attribution.
    """
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Format A: parenthesized attribution at line end
        m = re.search(r"\(([^()]+)\)\s*$", stripped)
        if m:
            meta = m.group(1).strip()
            if _POPE_NAME_RE.search(meta):
                return meta, idx

        # Format B: standalone attribution line — short, contains pope name,
        # has event markers (year, angelus, homily keywords, dash separator).
        # Must be short (< 100 chars) and contain no sentence body text.
        if (
            len(stripped) < 120
            and _POPE_NAME_RE.search(stripped)
            and re.search(
                r"\d{4}"                                # has a year
                r"|angelus|omelia|hom[eé]lie|homilía|homilia|predigt"
                r"|udienza|audience|audiencia|audience|publikumsaudienz"
                r"|meditazione|m[eé]ditation|meditación|meditação"
                r"|catechesi|catchèse|catequesis|katechese"
                r"|discorso|discourse|discours|discurso",
                stripped, re.IGNORECASE,
            )
        ):
            return stripped, idx

    return None, None


# ---------------------------------------------------------------------------
# Section-header helpers
# ---------------------------------------------------------------------------

def _strip_verse_refs_from_header(line: str, language: str = "it") -> str:
    """Strip trailing chapter/verse numbers from a reading section header line.

    After normalize_verse_refs() verse refs look like "1 1 a 13" or just "26".
    These are stripped from the END of the header so TTS announces only the
    book name (e.g. "dal libro della Genesi") without reading out the numbers.
    """
    range_word = re.escape(VERSE_RANGE_WORDS.get(language, "to"))
    # Full range: e.g. "1 1 a 13" or "10 46 à 52"
    line = re.sub(
        rf'\s+\d+\s+\d+\s+{range_word}\s+\d+\s*$', '', line, flags=re.IGNORECASE
    ).strip()
    # Chapter + verse only: e.g. "10 1"
    line = re.sub(r'\s+\d+\s+\d+\s*$', '', line).strip()
    # Just chapter/single number: e.g. "26"
    line = re.sub(r'\s+\d+\s*$', '', line).strip()
    return line


def _strip_section_verse_refs(section_text: str, language: str) -> str:
    """Apply verse-ref stripping to the first two lines of a section block.

    The first line is the section label ("Prima lettura") and the second is
    the book-source line ("Dal libro della Genesi 1 1 a 13").  Stripping
    trailing numbers from both ensures TTS only announces the book name.
    Lines that are purely an abbreviated book+verse reference (e.g. "Gn 37,3-4"
    or "Mt 21 33 a 43") are dropped entirely — they carry no speakable content.
    """
    # Lines that are purely a book reference (abbreviation or full name + verse
    # numbers) should be dropped — they carry no speakable content beyond
    # what the book-source header line already announced.
    #   Pattern A: short abbreviation, e.g. "Gn 37,3-4" or just "Gn"
    #   Pattern B: full capitalized book name (1-2 words) + verse numbers,
    #              e.g. "Matteo 21 33 a 43. 45-46" or "Giovanni Paolo 2 4"
    _abbrev_ref_re = re.compile(
        # Pattern A: optional leading digit + abbreviated book name + optional verse numbers
        # Matches: "Gn", "Gn 37,3-4", "2Re", "2Re 5,1-15a", "1Cor 5 1 a 10"
        r"^(?:\d+\s*)?[A-ZÀ-Ü][a-zà-ü]{0,4}(?:\s+\d[\d\s,;.:\-a-zA-Z]*)?\s*$"
        r"|"
        # Pattern B: full book name (1-2 capitalised words) + verse numbers
        # Matches: "Matteo 21 33 a 43"
        r"^[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)?\s+\d[\d\s,;.:\-a-zA-Z]*\s*$"
    )
    sec_lines = section_text.split("\n")
    # Strip trailing verse numbers from first two header lines
    for i in range(min(2, len(sec_lines))):
        sec_lines[i] = _strip_verse_refs_from_header(sec_lines[i], language)
    # Drop any of the first 4 lines that are purely abbreviated references
    cleaned: list[str] = []
    for i, line in enumerate(sec_lines):
        if i < 4 and line.strip() and _abbrev_ref_re.match(line.strip()):
            continue  # skip standalone abbreviated ref line
        cleaned.append(line)
    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Position-based section detection (for flat/single-paragraph feed texts)
# ---------------------------------------------------------------------------

def _find_inline_pos(text: str, pattern: str) -> int:
    """Find the start position of a section header pattern within flat text.

    Section patterns often use ``^`` anchors designed for line-start matching.
    This function tries each ``|``-separated alternative from left to right,
    preferring unanchored ones first, so that the globally-unique specific
    phrase (e.g. "dal vangelo" or "proclamação do evangelho") is matched before
    falling back to the more generic stripped-anchor version.

    Returns the character offset of the first match, or -1 if not found.
    """
    alts = pattern.split("|")
    # First pass: try alternatives that have NO leading ^ (already inline-safe)
    for alt in alts:
        if not alt.startswith("^"):
            m = re.search(alt, text, re.IGNORECASE)
            if m:
                return m.start()
    # Second pass: strip ^ from anchored alternatives and retry
    for alt in alts:
        if alt.startswith("^"):
            m = re.search(alt.lstrip("^"), text, re.IGNORECASE)
            if m:
                return m.start()
    return -1


def _strip_attribution_tail(text: str, meta: Optional[str], lang: str) -> str:
    """Remove the normalised pope attribution from the tail of pope-body text.

    After normalisation the parentheses in "(Papa Francesco, Angelus 2019)"
    are stripped, leaving the attribution text embedded at the end of the
    flat string.  This function finds and removes it so TTS does not read the
    attribution twice (it is announced separately in the segment header).
    """
    if not meta or not text:
        return text
    norm_meta = normalize_for_tts(meta, lang=lang)
    if norm_meta:
        # Direct suffix match (most common case)
        if text.endswith(norm_meta):
            return text[: -len(norm_meta)].strip()
        # Tolerate minor whitespace difference
        idx = text.rfind(norm_meta[:20])  # match on first 20 chars of meta
        if idx != -1:
            return text[:idx].strip()
    # Fallback: strip last occurrence of the first two words of the raw meta
    first_words = (meta.strip().split())[:2]
    if first_words:
        pattern = re.escape(" ".join(first_words))
        matches = list(re.finditer(rf'\b{pattern}\b', text, re.IGNORECASE))
        if matches:
            return text[: matches[-1].start()].strip()
    return text


def _build_segments_positional(
    flat_text: str,
    lang: str,
    patterns: dict,
    pre_comment_meta: Optional[str],
) -> list[str]:
    """Build liturgy segments from a single-paragraph (flat) text string.

    Used as a fallback when line-based detection cannot find the section
    headers (typically because the RSS feed provides the whole description
    as one paragraph with no HTML line-breaks between sections).
    """

    def find_pos(key: str) -> int:
        return _find_inline_pos(flat_text, patterns[key])

    pos_prima   = find_pos("prima")
    pos_seconda = find_pos("seconda")
    pos_salmo   = find_pos("salmo")
    pos_vangelo = find_pos("vangelo")

    if pos_prima == -1 or pos_vangelo == -1:
        return [flat_text]

    has_comment = pre_comment_meta is not None
    segments: list[str] = []

    # --- First reading ---
    # End boundary: seconda (if present and between prima/vangelo), then salmo,
    # then vangelo.  All positions must be strictly between prima and vangelo.
    if pos_seconda != -1 and pos_prima < pos_seconda < pos_vangelo:
        prima_end = pos_seconda
    elif pos_salmo != -1 and pos_prima < pos_salmo < pos_vangelo:
        prima_end = pos_salmo
    else:
        prima_end = pos_vangelo
    prima_section = _strip_section_verse_refs(flat_text[pos_prima:prima_end].strip(), lang)
    if prima_section:
        segments.append(prima_section)

    # --- Second reading (optional) ---
    if pos_seconda != -1 and pos_prima < pos_seconda < pos_vangelo:
        if pos_salmo != -1 and pos_seconda < pos_salmo < pos_vangelo:
            seconda_end = pos_salmo
        else:
            seconda_end = pos_vangelo
        seconda_section = _strip_section_verse_refs(
            flat_text[pos_seconda:seconda_end].strip(), lang
        )
        if seconda_section:
            segments.append(seconda_section)

    # --- Psalm is SKIPPED entirely ---

    # --- Gospel (split from pope comment body if closing phrase found) ---
    vangelo_raw = flat_text[pos_vangelo:]
    pope_body   = ""
    gospel_end  = len(vangelo_raw)  # default: no pope-body split

    if has_comment:
        closing_pat = GOSPEL_CLOSING_PATTERNS.get(lang)
        intro_pat   = POPE_COMMENT_INTRO_PATTERNS.get(lang)

        split_found = False
        # 1st heuristic: explicit gospel closing phrase (e.g. "Palavra da Salvação")
        if closing_pat:
            m = re.search(closing_pat, vangelo_raw, re.IGNORECASE)
            if m:
                gospel_end  = m.end()
                pope_body   = _strip_attribution_tail(
                    re.sub(r'^[\s.,;:]+', '', vangelo_raw[gospel_end:]),
                    pre_comment_meta, lang
                )
                split_found = True

        # 2nd heuristic: pope-comment opening phrase (e.g. "Irmãos e irmãs")
        if not split_found and intro_pat:
            m = re.search(intro_pat, vangelo_raw, re.IGNORECASE)
            if m:
                gospel_end  = m.start()
                pope_body   = _strip_attribution_tail(
                    vangelo_raw[gospel_end:].strip(), pre_comment_meta, lang
                )
                split_found = True

        # Fallback: no clean split — strip the attribution text from the end
        # of the gospel section so it is not spoken by TTS inside the gospel.
        if not split_found:
            gospel_end = len(
                _strip_attribution_tail(vangelo_raw, pre_comment_meta, lang)
            )

    vangelo_section = _strip_section_verse_refs(vangelo_raw[:gospel_end].strip(), lang)
    if vangelo_section:
        segments.append(vangelo_section)

    # --- Pope's comment ---
    if has_comment:
        comment_word, pope_title = POPE_COMMENT_LABELS.get(lang, POPE_COMMENT_LABELS["it"])
        pope_intro = pre_comment_meta.strip().replace(" - ", ", ")
        if not re.search(r"\b(papa|pope|pape|papst)\b", pope_intro, re.IGNORECASE):
            pope_intro = f"{pope_title} {pope_intro}"
        comment_section = f"__POPE__ {comment_word} {pope_intro}."
        if pope_body:
            comment_section = f"{comment_section}\n{pope_body}"
        segments.append(comment_section)

    return segments if segments else [flat_text]


def build_liturgy_segments(description: str, lang: str = "it") -> list[str]:
    """Split a liturgy description into spoken segments, skipping the psalm.

    Sections detected per language (prima lettura, optional seconda lettura,
    salmo – skipped entirely, vangelo, optional pope comment).
    Returns a list of normalised text strings to be read aloud with silence
    inserted between them by the audio generator.
    If no structure is detected the full text is returned as a single segment.

    Strategy
    --------
    1. Line-based detection: works when the RSS feed provides HTML line-breaks
       (``<br>`` / ``<p>``) that ``html_to_plain_text`` converts to ``\\n``.
    2. Positional fallback: used when the feed sends a single flat paragraph
       with no line-breaks.  Patterns are de-anchored (``^`` removed) so they
       can match anywhere in the text string.
    """
    # --- Extract pope comment attribution BEFORE normalisation strips parentheses ---
    # We use html_to_plain_text (which removes HTML tags like </p>) but NOT
    # normalize_for_tts (which would strip the parentheses we need).
    # For HTML-rich feeds the raw last line ends with </i></p> after the closing
    # ")" so the regex would fail on the raw HTML; the plain-text last line has
    # the attribution cleanly at the end (no trailing HTML tags).
    # For flat-text feeds (no HTML at all) both approaches are equivalent.
    plain_for_meta = html_to_plain_text(description)
    plain_meta_lines = [l.strip() for l in plain_for_meta.splitlines() if l.strip()]

    # Primary: check last line for parenthesized attribution "(Pope, Event)"
    plain_meta_last = plain_meta_lines[-1] if plain_meta_lines else plain_for_meta.strip()
    pre_comment_content_raw, pre_comment_meta = _extract_pope_meta(plain_meta_last)

    # Fallback: scan ALL lines for standalone attribution line (no parentheses)
    # This handles feeds that place "Benedetto XVI - Angelus, 8 luglio 2012"
    # as a plain line followed by the pope speech body.
    pre_comment_attr_line_idx: Optional[int] = None
    if pre_comment_meta is None:
        pre_comment_meta, pre_comment_attr_line_idx = _find_pope_attribution_in_lines(
            plain_meta_lines
        )
        if pre_comment_attr_line_idx is not None:
            pre_comment_content_raw = ""  # body comes after the attribution line

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

    # --- Positional fallback for flat (single-paragraph) feeds ---
    # Triggered when a section is not found (idx = -1) OR when prima and
    # vangelo land on the same line — which happens with flat text because an
    # unanchored alternative (e.g. "dal\s+vangelo") matches anywhere in the
    # single-line text while the prima anchor still fires at position 0.
    if idx_prima == -1 or idx_vangelo == -1 or idx_prima >= idx_vangelo:
        flat_text = " ".join(lines)
        return _build_segments_positional(flat_text, lang, patterns, pre_comment_meta)

    has_comment = pre_comment_meta is not None and idx_vangelo != -1

    # When attribution is a standalone line, locate it in the normalized lines
    # so we know where the gospel ends and where the pope body starts.
    # We look for the line containing the pope name after idx_vangelo.
    idx_attribution = -1
    if has_comment and pre_comment_attr_line_idx is not None:
        for li in range(idx_vangelo + 1, len(lines)):
            if _POPE_NAME_RE.search(lines[li]):
                idx_attribution = li
                break

    segments: list[str] = []

    # --- First reading ---
    if idx_seconda != -1 and idx_seconda > idx_prima:
        prima_end = idx_seconda
    elif idx_salmo != -1 and idx_salmo > idx_prima:
        prima_end = idx_salmo
    else:
        prima_end = idx_vangelo
    prima_section = _strip_section_verse_refs(
        "\n".join(lines[idx_prima:prima_end]).strip(), lang
    )
    if prima_section:
        segments.append(prima_section)

    # --- Second reading (optional) ---
    if idx_seconda != -1 and idx_seconda > idx_prima:
        if idx_salmo != -1 and idx_salmo > idx_seconda:
            seconda_end = idx_salmo
        else:
            seconda_end = idx_vangelo
        seconda_section = _strip_section_verse_refs(
            "\n".join(lines[idx_seconda:seconda_end]).strip(), lang
        )
        if seconda_section:
            segments.append(seconda_section)

    # --- Psalm is SKIPPED entirely ---

    # --- Gospel ---
    # Determine where the gospel text ends:
    #  - If attribution is a standalone line: ends at that line.
    #  - If attribution was at end via parentheses (last line): ends at len-1.
    #  - No comment: ends at len(lines).
    if not has_comment:
        vangelo_end = len(lines)
    elif idx_attribution != -1:
        vangelo_end = idx_attribution
    else:
        vangelo_end = len(lines) - 1

    vangelo_text = "\n".join(lines[idx_vangelo:vangelo_end]).strip()
    # For Italian feeds narrow to the actual gospel text after the header line
    if lang == "it":
        vangelo_match = re.search(r"dal\s+vangelo.*", vangelo_text, re.IGNORECASE | re.DOTALL)
        if vangelo_match:
            vangelo_text = vangelo_match.group(0).strip()
    vangelo_section = _strip_section_verse_refs(vangelo_text, lang)
    if vangelo_section:
        segments.append(vangelo_section)

    # --- Pope's comment ---
    if has_comment:
        comment_word, pope_title = POPE_COMMENT_LABELS.get(lang, POPE_COMMENT_LABELS["it"])
        pope_intro = pre_comment_meta.replace(" - ", ", ")
        if not re.search(r"\b(papa|pope|pape|papst)\b", pope_intro, re.IGNORECASE):
            pope_intro = f"{pope_title} {pope_intro}"
        comment_section = f"__POPE__ {comment_word} {pope_intro}."
        # Collect the pope body text:
        # - If attribution was a standalone line, the body is all lines after it.
        # - Otherwise use the raw content extracted by _extract_pope_meta.
        if idx_attribution != -1:
            # Body is everything after the attribution line.
            # These lines are already normalized — just join them.
            pope_body_lines = lines[idx_attribution + 1:]
            comment_content = " ".join(pope_body_lines).strip()
        else:
            # Normalise the raw comment content for TTS
            comment_content = normalize_for_tts(pre_comment_content_raw, lang=lang) if pre_comment_content_raw else ""
        if comment_content:
            comment_section = f"{comment_section}\n{comment_content}"
        segments.append(comment_section)

    return segments if segments else [text]


# Backward-compatible alias
def build_italian_liturgy_segments(description: str) -> list[str]:
    return build_liturgy_segments(description, lang="it")
