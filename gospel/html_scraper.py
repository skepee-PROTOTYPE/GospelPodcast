"""Vatican News HTML scraper for daily liturgy pages.

Instead of parsing the flat-text RSS description, this module fetches the
structured HTML page directly from Vatican News, which has clean <h2> section
headers separating the readings, gospel, and pope comment.

Page structure (one <h2> per section, all languages):
  IT: LETTURE DEL GIORNO  → VANGELO DEL GIORNO   → LE PAROLE DEI PAPI
  EN: READING OF THE DAY  → GOSPEL OF THE DAY     → THE WORDS OF THE POPES
  FR: LECTURE DU JOUR     → ÉVANGILE DU JOUR      → LES PAROLES DES PAPES
  ES: LECTURA DEL DÍA     → EVANGELIO DEL DÍA     → LAS PALABRAS DE LOS PAPAS
  PT: LEITURA DO DIA      → EVANGELHO DO DIA      → AS PALAVRAS DOS PAPAS
  DE: TAGESLESUNG         → EVANGELIUM VOM TAG    → WORTE DER PÄPSTE

The psalm section is always embedded inside the reading section and is cut
before normalization.  A potential second reading (Sundays / major feasts) is
split off and emitted as a separate segment.
"""

import datetime
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from gospel.text_normalizer import (
    _extract_pope_meta,
    _find_pope_attribution_in_lines,
    _strip_section_verse_refs,
    html_to_plain_text,
    normalize_for_tts,
    POPE_COMMENT_LABELS,
)

# ---------------------------------------------------------------------------
# Per-language page configuration
# ---------------------------------------------------------------------------

_LANG_CFG: dict[str, dict] = {
    "it": {
        "slug":       "vangelo-del-giorno-e-parola-del-giorno",
        "h2_reading": "LETTURE DEL GIORNO",
        "h2_gospel":  "VANGELO DEL GIORNO",
        "h2_pope":    "LE PAROLE DEI PAPI",
        "psalm_rx":   r"salmo\s+responsorial",
        "seconda_rx": r"seconda\s+lettura",
        "prima_rx":   r"^prima\s+lettura",
    },
    "en": {
        "slug":       "word-of-the-day",
        "h2_reading": "READING OF THE DAY",
        "h2_gospel":  "GOSPEL OF THE DAY",
        "h2_pope":    "THE WORDS OF THE POPES",
        "psalm_rx":   r"responsorial\s+psalm",
        "seconda_rx": r"second\s+reading",
        # English pages often label both readings "A reading from X" with no
        # explicit "Second reading" heading – use this as a fallback split.
        "prima_rx":   r"^a\s+reading\s+from|^first\s+reading",
    },
    "fr": {
        "slug":       "evangile-du-jour",
        "h2_reading": "LECTURE DU JOUR",
        "h2_gospel":  "ÉVANGILE DU JOUR",
        "h2_pope":    "LES PAROLES DES PAPES",
        "psalm_rx":   r"psaume\b",
        "seconda_rx": r"deuxi[eè]me\s+lecture",
        "prima_rx":   r"^premi[eè]re?\s+lecture|^lecture\s+(du|de|d')",
    },
    "es": {
        "slug":       "evangelio-de-hoy",
        "h2_reading": "LECTURA DEL DÍA",
        "h2_gospel":  "EVANGELIO DEL DÍA",
        "h2_pope":    "LAS PALABRAS DE LOS PAPAS",
        "psalm_rx":   r"salmo\s+responsorial",
        "seconda_rx": r"segunda\s+lectura",
        "prima_rx":   r"^primera\s+lectura|^lectura\s+de",
    },
    "pt": {
        "slug":       "palavra-do-dia",
        "h2_reading": "LEITURA DO DIA",
        "h2_gospel":  "EVANGELHO DO DIA",
        "h2_pope":    "AS PALAVRAS DOS PAPAS",
        "psalm_rx":   r"salmo\s+responsorial",
        "seconda_rx": r"segunda\s+leitura",
        "prima_rx":   r"^primeira\s+leitura|^leitura\s+d",
    },
    "de": {
        "slug":       "tagesevangelium-und-tagesliturgie",
        "h2_reading": "TAGESLESUNG",
        "h2_gospel":  "EVANGELIUM VOM TAG",
        "h2_pope":    "WORTE DER PÄPSTE",
        "psalm_rx":   r"antwortpsalm",
        "seconda_rx": r"zweite\s+lesung",
        "prima_rx":   r"^(erste\s+)?lesung\s+aus",
    },
}

_BASE_URL = "https://www.vaticannews.va"

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GospelPodcastBot/1.0; "
        "+https://github.com/marcellobr/gospelpodcast)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "it,en;q=0.9",
}

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def day_url(lang: str, date: datetime.date) -> str:
    """Return the Vatican News HTML URL for *lang* on *date*."""
    cfg = _LANG_CFG.get(lang)
    if not cfg:
        raise ValueError(f"Language {lang!r} not supported. Choices: {sorted(_LANG_CFG)}")
    slug = cfg["slug"]
    return (
        f"{_BASE_URL}/{lang}/{slug}"
        f"/{date.year}/{date.month:02d}/{date.day:02d}.html"
    )


def _fetch(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    # Vatican News pages are always UTF-8; force the encoding so that
    # resp.text does not mis-decode accented characters as latin-1.
    return resp.content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# BeautifulSoup helpers
# ---------------------------------------------------------------------------


def _find_h2(soup: BeautifulSoup, keyword: str) -> Optional[object]:
    """Return the first <h2> whose text contains *keyword* (case-insensitive)."""
    kw = keyword.strip().lower()
    for h2 in soup.find_all("h2"):
        if kw in h2.get_text(" ", strip=True).lower():
            return h2
    return None


def _collect_section_html(h2_elem) -> str:
    """Collect raw HTML content from the section that contains *h2_elem*.

    Vatican News wraps each liturgy section as::

        <section class="section--isStatic">
            <div class="section__head"><h2>Section Title</h2></div>
            <div class="section__wrapper"><!-- readable content --></div>
        </section>

    Strategy:
    1. Navigate h2 → parent(section__head) → grandparent(section)
       and return the ``section__wrapper`` div's inner HTML.
    2. If the wrapper div is not found, try sibling divs of the head.
    3. Fall back to plain ``h2.next_siblings`` (flat layout).
    """
    # Strategy 1: Vatican News section layout
    head_div = h2_elem.parent
    if head_div is not None:
        section = head_div.parent
        if section is not None:
            # Find section__wrapper (or any sibling div of section__head that has content)
            wrapper = section.find(class_="section__wrapper")
            if wrapper and wrapper.get_text(strip=True):
                return str(wrapper)
            # Try any sibling div of head_div that is not the head itself
            for child in section.children:
                if child is head_div:
                    continue
                if getattr(child, "name", None) == "div" and child.get_text(strip=True):
                    return str(child)

    # Strategy 2: h2 siblings at the same DOM level (flat layout)
    parts = []
    for sib in h2_elem.next_siblings:
        if getattr(sib, "name", None) == "h2":
            break
        parts.append(str(sib))
    return "".join(parts)


def _remove_verse_ref_inlines(soup_elem) -> None:
    """Decompose inline elements that contain only verse references.

    Examples: <span>2Re 5,1-15a</span>, <span>Lc 4,24-30</span>.

    These appear inline inside book-source lines and would be concatenated
    directly onto the book name by html_to_plain_text, producing strings like
    "Dal secondo libro dei Re 2Re 5 1 a 15" that the verse-stripping logic
    cannot fully clean.  Removing them at the DOM level is the cleanest fix.
    The book name line already provides enough context for TTS.
    """
    for tag in soup_elem.find_all(["span", "sup", "small"]):
        txt = tag.get_text("", strip=True)
        # Match: optional leading digit + abbreviated/full book name + verse numbers
        # e.g. "2Re 5,1-15a", "Lc 4,24-30", "Mt 21,33-43", "Salmo 41"
        if re.match(
            r"^\d*[A-ZÀ-Ü][a-zà-ü]{1,6}\s+\d[\d,;:.\-a-zA-Z\s]*$",
            txt,
        ):
            tag.decompose()


def _split_readings(read_plain: str, cfg: dict) -> tuple[str, str]:
    """Split a reading section into (first_reading, second_reading), discarding the psalm.

    Vatican News presents readings in one of three layouts:

    **Weekday** (single reading)::

        Prima Lettura …
        Salmo Responsoriale …      ← psalm: skip

    **Sunday / feast** (two readings, explicit labels)::

        Prima Lettura …
        Salmo Responsoriale …      ← psalm between the two (skip it)
        Seconda Lettura …

    **Sunday / feast, EN-style** (two readings, same "A reading from" label)::

        A reading from Book 1 …    ← no psalm, no "Second reading" heading
        A reading from Book 2 …

    Returns ``(first_raw, seconda_raw)``; ``seconda_raw`` is ``""`` on weekdays.
    """
    psalm_m   = re.search(cfg["psalm_rx"],   read_plain, re.IGNORECASE)
    seconda_m = re.search(cfg["seconda_rx"], read_plain, re.IGNORECASE)

    psalm_pos   = psalm_m.start()   if psalm_m   else len(read_plain)
    seconda_pos = seconda_m.start() if seconda_m else -1

    if seconda_pos != -1:
        if seconda_pos > psalm_pos:
            # Sunday/feast: Prima → Psalm → Seconda
            first_raw   = read_plain[:psalm_pos].strip()
            seconda_raw = read_plain[seconda_pos:].strip()
        else:
            # Unusual: Seconda appears before Psalm → Prima + Seconda cut at psalm
            first_raw   = read_plain[:seconda_pos].strip()
            seconda_raw = read_plain[seconda_pos:psalm_pos].strip()
        return first_raw, seconda_raw

    if psalm_m:
        # Weekday: only first reading; cut at psalm
        return read_plain[:psalm_pos].strip(), ""

    # No psalm marker and no explicit "Second reading" label found.
    # Some language pages (e.g. English Vatican News) label every reading as
    # "A reading from …" without an explicit ordinal.  Detect a second reading
    # by looking for a second hit of the prima_rx pattern.
    prima_rx = cfg.get("prima_rx")
    if prima_rx:
        hits = list(re.finditer(prima_rx, read_plain, re.IGNORECASE | re.MULTILINE))
        if len(hits) >= 2:
            split_pos = hits[1].start()
            return read_plain[:split_pos].strip(), read_plain[split_pos:].strip()

    # Single reading, no psalm visible
    return read_plain.strip(), ""


def _section_plain(h2_elem) -> str:
    """Extract plain multiline text from the section bounded by *h2_elem*.

    Removes inline verse-reference tags before text extraction so the book
    name is not contaminated with concatenated abbreviations.
    """
    html_chunk = _collect_section_html(h2_elem)
    if not html_chunk.strip():
        return ""
    sec_soup = BeautifulSoup(html_chunk, "html.parser")
    _remove_verse_ref_inlines(sec_soup)
    return html_to_plain_text(str(sec_soup))


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _cut_at_pattern(text: str, pattern: str) -> str:
    """Return *text* truncated just before the first match of *pattern*."""
    m = re.search(pattern, text, re.IGNORECASE)
    return text[: m.start()].strip() if m else text.strip()


def _split_at_pattern(text: str, pattern: str) -> tuple[str, str]:
    """Split *text* at the first match of *pattern*.

    Returns ``(before.strip(), from_match.strip())``, or
    ``(text.strip(), "")`` when *pattern* is not found.
    """
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return text.strip(), ""
    return text[: m.start()].strip(), text[m.start():].strip()


def _pope_segment(pope_plain: str, lang: str) -> Optional[str]:
    """Build a ``__POPE__`` segment from raw plain-text pope-section content.

    Detects the attribution via parenthesized format ``(Pope Name - Event)``
    (primary) or standalone attribution line (secondary).  Returns ``None``
    if no recognisable pope attribution is found.
    """
    lines = [ln.strip() for ln in pope_plain.splitlines() if ln.strip()]
    if not lines:
        return None

    # Primary: parenthesized attribution at the end of the last line
    content_before_meta, meta = _extract_pope_meta(lines[-1])
    if meta is not None:
        # The body and attribution may be in the same paragraph (single line).
        # content_before_meta holds the body text from that line (before the
        # closing parenthetical); lines[:-1] holds any preceding paragraphs.
        preceding = "\n".join(lines[:-1])
        if content_before_meta.strip():
            body_text = (preceding + "\n" + content_before_meta).strip()
        else:
            body_text = preceding
    else:
        # Secondary: standalone attribution line anywhere in the section
        meta, attr_idx = _find_pope_attribution_in_lines(lines)
        if meta is None:
            return None
        body_text = "\n".join(lines[:attr_idx])

    comment_word, pope_title = POPE_COMMENT_LABELS.get(lang, POPE_COMMENT_LABELS["it"])
    pope_intro = meta.strip().replace(" - ", ", ")
    if not re.search(r"\b(papa|pope|pape|papst)\b", pope_intro, re.IGNORECASE):
        pope_intro = f"{pope_title} {pope_intro}"
    header = f"__POPE__ {comment_word} {pope_intro}."

    body_norm = (
        normalize_for_tts(body_text, lang=lang, flatten_lines=True)
        if body_text.strip()
        else ""
    )
    return f"{header}\n{body_norm}" if body_norm else header


def _extract_title(soup: BeautifulSoup, lang: str, date: datetime.date) -> str:
    """Extract the liturgical day title from the page.

    Strategy:
    1. Look for Vatican News's ``indicazioneLiturgica`` element which contains
       the liturgical day name (e.g. "Lunedì della terza settimana di Quaresima").
    2. Regex over the full page text for DD/MM/YYYY followed by a description.
    3. Fall back to a plain formatted date.
    """
    # Strategy 1: Vatican News specific element (consistent across all languages)
    il_elem = soup.find(class_="indicazioneLiturgica")
    if il_elem:
        day_desc = il_elem.get_text(" ", strip=True).strip()
        if day_desc and len(day_desc) < 120:
            return normalize_for_tts(day_desc, lang=lang)

    # Strategy 2: regex over full page text
    date_str = date.strftime("%d/%m/%Y")
    full_text = soup.get_text(" ", strip=True)
    m = re.search(
        re.escape(date_str) + r"\s+([^\s].{5,80}?)(?:\s{2,}|\Z)",
        full_text,
    )
    if m:
        day_desc = m.group(1).strip()
        if day_desc and len(day_desc) < 120:
            return normalize_for_tts(day_desc, lang=lang)

    # Strategy 3: plain date fallback
    try:
        date_fmt = date.strftime("%-d %B %Y")
    except ValueError:
        date_fmt = date.strftime("%d %B %Y")
    return normalize_for_tts(date_fmt, lang=lang)


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------


class VaticanHTMLScraper:
    """Fetch daily liturgy segments directly from Vatican News HTML pages.

    Usage::

        scraper = VaticanHTMLScraper("it")
        title, segments = scraper.fetch_segments()
        episode = audio_gen.create_episode_from_segments(title, segments)
    """

    def __init__(self, lang: str):
        if lang not in _LANG_CFG:
            raise ValueError(
                f"Language {lang!r} not supported. Choices: {sorted(_LANG_CFG)}"
            )
        self.lang = lang
        self._cfg = _LANG_CFG[lang]

    def day_url(self, date: Optional[datetime.date] = None) -> str:
        """Return the Vatican News URL for today (or *date*)."""
        return day_url(self.lang, date or datetime.date.today())

    def fetch_segments(
        self, date: Optional[datetime.date] = None
    ) -> tuple[str, list[str]]:
        """Fetch the Vatican News page and return ``(title, segments)``.

        *segments* is a list of normalised text blocks — one per liturgy
        section (reading(s), gospel, pope comment) — ready to pass directly to
        ``AudioGenerator.create_episode_from_segments()``.

        Raises
        ------
        requests.HTTPError
            When the page cannot be fetched (e.g. 404 for a future date).
        RuntimeError
            When the page is fetched but no liturgy content is recognised.
        """
        if date is None:
            date = datetime.date.today()

        url = self.day_url(date)
        html = _fetch(url)
        soup = BeautifulSoup(html, "html.parser")

        cfg = self._cfg
        lang = self.lang
        segments: list[str] = []

        # --- Title ---
        title = _extract_title(soup, lang, date)

        # --- Reading section ---
        h2_read = _find_h2(soup, cfg["h2_reading"])
        if h2_read:
            read_plain = _section_plain(h2_read)
            # Extract first and optional second reading, skipping the psalm.
            # Sunday/feast structure is: Prima → Psalm → Seconda
            # Weekday structure is:      Prima → Psalm
            first_raw, seconda_raw = _split_readings(read_plain, cfg)
            if first_raw:
                first_norm = _strip_section_verse_refs(
                    normalize_for_tts(first_raw, lang=lang, flatten_lines=False),
                    lang,
                )
                if first_norm.strip():
                    segments.append(first_norm)
            if seconda_raw:
                seconda_norm = _strip_section_verse_refs(
                    normalize_for_tts(seconda_raw, lang=lang, flatten_lines=False),
                    lang,
                )
                if seconda_norm.strip():
                    segments.append(seconda_norm)

        # --- Gospel section ---
        h2_gospel = _find_h2(soup, cfg["h2_gospel"])
        if h2_gospel:
            gospel_plain = _section_plain(h2_gospel)
            gospel_norm = _strip_section_verse_refs(
                normalize_for_tts(gospel_plain, lang=lang, flatten_lines=False),
                lang,
            )
            if gospel_norm.strip():
                segments.append(gospel_norm)

        # --- Pope section ---
        h2_pope = _find_h2(soup, cfg["h2_pope"])
        if h2_pope:
            pope_plain = _section_plain(h2_pope)
            pope_seg = _pope_segment(pope_plain, lang)
            if pope_seg:
                segments.append(pope_seg)

        if not segments:
            raise RuntimeError(
                f"No liturgy content found at {url}. "
                "The page structure may have changed."
            )

        return title, segments
