"""Vatican News HTML scraper for Saint of the Day pages.

Listing page URL pattern (per language):
  IT: https://www.vaticannews.va/it/santo-del-giorno/{MM}/{DD}.html
  EN: https://www.vaticannews.va/en/saints/{MM}/{DD}.html
  FR: https://www.vaticannews.va/fr/saint-du-jour/{MM}/{DD}.html
  ES: https://www.vaticannews.va/es/santos/{MM}/{DD}.html
  PT: https://www.vaticannews.va/pt/santo-do-dia/{MM}/{DD}.html
  DE: https://www.vaticannews.va/de/tagesheiliger/{MM}/{DD}.html

Listing page structure (one or more saints):
  <section class="section--isStatic">
      <div class="section__head"><h2>SAINT NAME (ALL CAPS)</h2></div>
      <div class="section__wrapper">
          <p>Brief biography (2-3 sentences).</p>
          <a href="/it/santo-del-giorno/MM/DD/slug.html">Full page link</a>
      </div>
  </section>

Individual saint page has the same layout plus multiple <h2> biography
sub-sections ("Il clandestino del Vangelo", "Amore e tradimento", etc.) each
with their own section__wrapper.

On some language editions (e.g. German), a saint may only appear as a link
in the listing intro paragraph rather than as a full h2 section — the scraper
handles this by scanning all saint detail links on the page.
"""

import datetime
import re
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from gospel.text_normalizer import html_to_plain_text, normalize_for_tts

# ---------------------------------------------------------------------------
# Per-language configuration
# ---------------------------------------------------------------------------

_LANG_CFG: Dict[str, Dict] = {
    "it": {
        "slug":         "santo-del-giorno",
        "page_title":   "Santo del Giorno",
        "detail_slug":  "santo-del-giorno",
    },
    "en": {
        "slug":         "saints",
        "page_title":   "Saint of the Day",
        "detail_slug":  "saints",
    },
    "fr": {
        "slug":         "saint-du-jour",
        "page_title":   "Saint du Jour",
        "detail_slug":  "saint-du-jour",
    },
    "es": {
        "slug":         "santos",
        "page_title":   "Santos del Día",
        "detail_slug":  "santos",
    },
    "pt": {
        "slug":         "santo-do-dia",
        "page_title":   "Santo do Dia",
        "detail_slug":  "santo-do-dia",
    },
    "de": {
        "slug":         "tagesheiliger",
        "page_title":   "Tagesheiliger",
        "detail_slug":  "tagesheiliger",
    },
}

# Month names per language for episode title formatting
_MONTH_NAMES: Dict[str, List[str]] = {
    "it": ["gennaio","febbraio","marzo","aprile","maggio","giugno",
           "luglio","agosto","settembre","ottobre","novembre","dicembre"],
    "en": ["January","February","March","April","May","June",
           "July","August","September","October","November","December"],
    "fr": ["janvier","février","mars","avril","mai","juin",
           "juillet","août","septembre","octobre","novembre","décembre"],
    "es": ["enero","febrero","marzo","abril","mayo","junio",
           "julio","agosto","septiembre","octubre","noviembre","diciembre"],
    "pt": ["janeiro","fevereiro","março","abril","maio","junho",
           "julho","agosto","setembro","outubro","novembro","dezembro"],
    "de": ["Januar","Februar","März","April","Mai","Juni",
           "Juli","August","September","Oktober","November","Dezember"],
}

_BASE_URL = "https://www.vaticannews.va"

# Minimal sentence used when a saint has no biography text available
# (e.g. English Vatican News pages, which have no static biography content).
_MINIMAL_SEGMENT_TEMPLATE: Dict[str, str] = {
    "it": "Oggi la Chiesa celebra {name}.",
    "en": "Today the Church celebrates {name}.",
    "fr": "Aujourd'hui l'Église célèbre {name}.",
    "es": "Hoy la Iglesia celebra {name}.",
    "pt": "Hoje a Igreja celebra {name}.",
    "de": "Heute feiert die Kirche {name}.",
}

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GospelPodcastBot/1.0; "
        "+https://github.com/marcellobr/gospelpodcast)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "it,en;q=0.9",
}

# Navigation h2 keywords that appear on listing pages but are NOT saints.
# Match is done on the lowercased h2 text using `in` (substring match).
_NAV_KEYWORDS_LC = {
    # Event / live-streaming sections
    "udienza generale", "general audience", "audiences générales",
    "audiencias generales", "audiência geral", "generalaudienz",
    "angelus", "rosario", "rosary", "live", "eventi",
    # Navigation UI elements
    "cerca", "search", "suche", "recherche", "busca", "buscar",
    "menu", "navigation",
    # Page-title h2s (the listing page repeats the title as an h2 at the top)
    "santo del giorno", "saint of the day", "saint du jour",
    "santo del día", "santo do dia", "tagesheiliger",
    # Common promo / sidebar sections
    "additional links", "other events", "altri eventi", "upcoming",
}


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def day_url(lang: str, date: datetime.date) -> str:
    """Return the Vatican News saint-of-the-day listing URL for *lang* on *date*."""
    cfg = _LANG_CFG.get(lang)
    if not cfg:
        raise ValueError(f"Language {lang!r} not supported. Choices: {sorted(_LANG_CFG)}")
    slug = cfg["slug"]
    return f"{_BASE_URL}/{lang}/{slug}/{date.month:02d}/{date.day:02d}.html"


def _format_date(date: datetime.date, lang: str) -> str:
    """Format date as a spoken string in the given language."""
    month_names = _MONTH_NAMES.get(lang, _MONTH_NAMES["en"])
    month_name = month_names[date.month - 1]
    if lang == "en":
        return f"{month_name} {date.day}, {date.year}"
    elif lang == "de":
        return f"{date.day}. {month_name} {date.year}"
    elif lang in ("es",):
        return f"{date.day} de {month_name} de {date.year}"
    elif lang in ("pt",):
        return f"{date.day} de {month_name} de {date.year}"
    else:  # it, fr
        return f"{date.day} {month_name} {date.year}"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=_HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def _is_nav_h2(text: str) -> bool:
    """Return True if this h2 text belongs to navigation/event section (not a saint)."""
    lower = text.strip().lower()
    # Short keyword match
    if any(kw in lower for kw in _NAV_KEYWORDS_LC):
        return True
    # Navigation sections tend to be very short and in title-case (not all-caps)
    # Saints are typically ALL-CAPS on the listing page
    return False


def _is_saint_detail_link(href: str, lang: str) -> bool:
    """Return True if *href* points to an individual saint hagiography page."""
    slug = _LANG_CFG.get(lang, {}).get("detail_slug", "")
    if not slug:
        return False
    # Pattern: /{lang}/{slug}/{MM}/{DD}/something.html
    pattern = rf"/{re.escape(lang)}/{re.escape(slug)}/\d{{2}}/\d{{2}}/.+\.html"
    return bool(re.search(pattern, href))


def _collect_wrapper_html(h2_elem) -> str:
    """Collect the section__wrapper HTML for the section that contains *h2_elem*.

    Vatican News wraps each section as:
        <section class="section--isStatic">
            <div class="section__head"><h2>Title</h2></div>
            <div class="section__wrapper">content</div>
        </section>

    Falls back to h2.next_siblings if the wrapper is not found.
    """
    head_div = h2_elem.parent
    if head_div is not None:
        section = head_div.parent
        if section is not None:
            wrapper = section.find(class_="section__wrapper")
            if wrapper and wrapper.get_text(strip=True):
                return str(wrapper)
            # Try any sibling div of head_div that has content
            for child in section.children:
                if child is head_div:
                    continue
                if getattr(child, "name", None) == "div" and child.get_text(strip=True):
                    return str(child)

    # Flat layout fallback: gather sibling elements until the next h2
    parts = []
    for sib in h2_elem.next_siblings:
        if getattr(sib, "name", None) == "h2":
            break
        parts.append(str(sib))
    return "".join(parts)


def _extract_detail_link(wrapper_html: str, lang: str) -> Optional[str]:
    """Find the individual-saint detail URL inside *wrapper_html*.

    Vatican News renders read-more links as:
        <a class="saintReadMore" href="/{lang}/{slug}/MM/DD/name.html">Leggi Tutto...</a>
        (Italian: "Leggi Tutto", French: "Tout lire", Spanish: "Leer todo",
         Portuguese: "Ler tudo", German: "Alles lesen")
    We prioritise these canonical read-more links; fall back to any saint URL.
    """
    soup = BeautifulSoup(wrapper_html, "html.parser")
    # Priority 1: explicit read-more link (class="saintReadMore")
    rm = soup.find("a", class_="saintReadMore", href=True)
    if rm:
        href = rm["href"]
        return href if href.startswith("http") else f"{_BASE_URL}{href}"
    # Priority 2: any link matching the saint detail URL pattern
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if _is_saint_detail_link(href, lang):
            return href if href.startswith("http") else f"{_BASE_URL}{href}"
    return None


# Transliteration map for accented / special characters used in Vatican News slugs.
_TRANSLIT: Dict[str, str] = {
    "à":"a","á":"a","â":"a","ã":"a","ä":"ae","å":"a","æ":"ae",
    "ç":"c","è":"e","é":"e","ê":"e","ë":"e","ì":"i","í":"i","î":"i","ï":"i",
    "ñ":"n","ò":"o","ó":"o","ô":"o","õ":"o","ö":"oe","ø":"o",
    "ù":"u","ú":"u","û":"u","ü":"ue","ý":"y","ÿ":"y",
    "ß":"ss","œ":"oe",
}


def _name_to_slug(name: str) -> str:
    """Convert a saint name to the Vatican News URL slug format.

    Vatican News consistently uses:
        "St. John Ogilvie, Jesuit and Martyr"
        → "st--john-ogilvie--jesuit-and-martyr"

    Rules observed:
    1. Lowercase
    2. Periods (.) → "--"   (e.g., "St." → "st--")
    3. Commas (,) → "--"    (title/role separator)
    4. Spaces → "-"
    5. Transliterate accented chars (ä→ae, ü→ue, etc.)
    6. Remove remaining non-alphanumeric except hyphens
    7. Collapse 3+ consecutive hyphens → "--"
    8. Strip leading/trailing hyphens
    """
    s = name.lower()
    s = "".join(_TRANSLIT.get(c, c) for c in s)
    s = s.replace(".", "--").replace(",", "--")
    s = s.replace(" ", "-")
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{3,}", "--", s)
    return s.strip("-")


def _try_detail_url(
    lang: str, date: datetime.date, saint_h2_text: str
) -> Optional[str]:
    """Construct and verify a detail page URL from the saint name slug.

    Returns the URL if it responds with HTTP 200, otherwise None.
    Suppresses network errors silently.
    """
    slug = _name_to_slug(saint_h2_text)
    cfg = _LANG_CFG.get(lang, {})
    detail_slug = cfg.get("detail_slug", cfg.get("slug", ""))
    url = (
        f"{_BASE_URL}/{lang}/{detail_slug}"
        f"/{date.month:02d}/{date.day:02d}/{slug}.html"
    )
    try:
        resp = requests.head(url, headers=_HTTP_HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code == 200:
            return url
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Listing-page saint discovery
# ---------------------------------------------------------------------------

def _parse_saint_sections(
    soup: BeautifulSoup, lang: str, date: Optional[datetime.date] = None
) -> List[Dict]:
    """Extract all saints from a listing page.

    Returns a list of dicts:
        {
            "name":        str,            # Saint name (title-cased for TTS)
            "brief":       str,            # Brief description (plain text)
            "detail_url":  Optional[str],  # URL to full hagiography page
        }
    """
    saints: List[Dict] = []
    seen_detail_urls: set = set()

    # --- Pass 1: find all h2 sections that look like saints ---
    for h2 in soup.find_all("h2"):
        h2_text = h2.get_text(" ", strip=True)
        if not h2_text or _is_nav_h2(h2_text):
            continue
        # Skip very long h2s (they're likely article titles, not saint names)
        if len(h2_text) > 120:
            continue

        wrapper_html = _collect_wrapper_html(h2)
        brief_text = html_to_plain_text(wrapper_html).strip() if wrapper_html else ""
        detail_url = _extract_detail_link(wrapper_html, lang) if wrapper_html else None
        if detail_url:
            seen_detail_urls.add(detail_url)

        # Also check if the h2 is wrapped by an ancestor <a> link (German Vatican News
        # renders "Hl. Simplicius, Papst >" as:
        #   <a href="..."><div class="section__head"><h2>...<h2></div></a>)
        # OR if the h2 contains a child <a> link.
        if not detail_url:
            candidate_a = h2.find("a", href=True)  # link inside h2
            if not candidate_a:
                # Walk up ancestors, stopping at the section--isStatic boundary
                for ancestor in h2.parents:
                    if getattr(ancestor, "name", None) == "a":
                        candidate_a = ancestor
                        break
                    classes = ancestor.get("class", []) if hasattr(ancestor, "get") else []
                    if "section--isStatic" in classes:
                        break
            if candidate_a is not None:
                a_href = candidate_a.get("href", "") if hasattr(candidate_a, "get") else ""
                if a_href and _is_saint_detail_link(a_href, lang):
                    detail_url = a_href if a_href.startswith("http") else f"{_BASE_URL}{a_href}"
                    seen_detail_urls.add(detail_url)
                    # Strip trailing UI arrow indicators from the name (e.g. ">")
                    h2_text = h2_text.rstrip(" >→»").strip()

        # If no detail link was found via HTML inspection, try constructing the URL
        # from the saint name slug (covers languages like English whose listing
        # pages have names but no biographical text or individual page links).
        if not detail_url and date:
            detail_url = _try_detail_url(lang, date, h2_text)
            if detail_url:
                seen_detail_urls.add(detail_url)

        # Include all saints that passed the _is_nav_h2 filter regardless of
        # whether we found content. fetch_saints() will apply a minimal fallback
        # if no biography is available.

        # Convert all-caps saint name to title-case for TTS
        name_tts = h2_text.title() if h2_text.isupper() else h2_text

        saints.append({
            "name":       name_tts,
            "brief":      brief_text,
            "detail_url": detail_url,
        })

    # --- Pass 2: scan whole page for saint detail links not yet found ---
    # (Handles German-style pages where some saints only appear as links)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _is_saint_detail_link(href, lang):
            continue
        full_url = href if href.startswith("http") else f"{_BASE_URL}{href}"
        if full_url in seen_detail_urls:
            continue
        # This saint wasn't found via h2 — we only have a link
        link_text = a.get_text(" ", strip=True)
        name_tts = link_text.title() if link_text.isupper() else link_text
        if not name_tts:
            name_tts = "Unknown Saint"
        saints.append({
            "name":       name_tts,
            "brief":      "",           # Will be fetched from detail page
            "detail_url": full_url,
        })
        seen_detail_urls.add(full_url)

    return saints


# ---------------------------------------------------------------------------
# Individual saint detail page parsing
# ---------------------------------------------------------------------------

def _fetch_detail_text(url: str, lang: str) -> str:
    """Fetch a saint's individual page and return the full biography as plain text.

    The page has:
      - An intro paragraph (sometimes inside the first section__wrapper)
      - Multiple biography sub-sections (h2 + section__wrapper each)
    We concatenate all non-navigation text in document order.
    """
    try:
        raw_html = _fetch(url)
    except Exception:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")
    text_parts: List[str] = []

    # Collect from section--isStatic sections (Vatican News structured layout)
    for section in soup.find_all(class_="section--isStatic"):
        h2 = section.find("h2")
        h2_text = h2.get_text(" ", strip=True) if h2 else ""
        if h2_text and _is_nav_h2(h2_text):
            continue

        wrapper = section.find(class_="section__wrapper")
        if not wrapper:
            # Try any div that is not the section__head
            head = section.find(class_="section__head")
            for div in section.find_all("div", recursive=False):
                if div is not head and div.get_text(strip=True):
                    wrapper = div
                    break

        if wrapper:
            text = html_to_plain_text(str(wrapper)).strip()
            # Filter out short texts (navigation links, share prompts, etc.)
            if text and len(text) >= 60:
                text_parts.append(text)

    if text_parts:
        return "\n\n".join(text_parts)

    # Broad fallback: collect <p> tags from the body with meaningful content
    paragraphs: List[str] = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        # Skip short/nav paragraphs and donation prompts
        if len(t) >= 60 and "http" not in t:
            paragraphs.append(t)
    return "\n".join(paragraphs[:30])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_saints(
    lang: str,
    date: Optional[datetime.date] = None,
    fetch_detail: bool = True,
) -> Tuple[str, List[str]]:
    """Fetch and build podcast segments for the saint(s) of *date* in *lang*.

    Parameters
    ----------
    lang:
        Language code: it | en | fr | es | pt | de
    date:
        Date to fetch (default: today).
    fetch_detail:
        If True, fetch individual saint pages for the full biography.
        If False, use only the brief listing-page summary.

    Returns
    -------
    (episode_title, segments)
        *episode_title* is a human-readable title string (not yet TTS-normalised).
        *segments* is a list of strings ready for
        :class:`~gospel.audio_generator.AudioGenerator.create_episode_from_segments`.
        Each segment has the saint name on the first line followed by the
        biography text on subsequent lines.
    """
    if date is None:
        date = datetime.date.today()

    cfg = _LANG_CFG.get(lang)
    if not cfg:
        raise ValueError(f"Language {lang!r} not supported. Choices: {sorted(_LANG_CFG)}")

    url = day_url(lang, date)
    raw_html = _fetch(url)
    soup = BeautifulSoup(raw_html, "html.parser")

    saints = _parse_saint_sections(soup, lang, date=date)
    if not saints:
        raise ValueError(f"No saints found for {lang} on {date} (URL: {url})")

    segments: List[str] = []
    saint_names: List[str] = []

    for saint in saints:
        name_raw = saint["name"]
        brief_raw = saint["brief"]
        detail_url = saint.get("detail_url")

        # Build biography text: prefer full detail page if available
        bio_text = ""
        if fetch_detail and detail_url:
            bio_text = _fetch_detail_text(detail_url, lang)
        if not bio_text.strip():
            bio_text = brief_raw

        # Normalise name for TTS first (used in fallback template too)
        name_tts = normalize_for_tts(name_raw, lang=lang, flatten_lines=True)

        if not bio_text.strip():
            # No biography found on Vatican News for this saint/language.
            # Emit a minimal announcement (name + celebration phrase) rather
            # than skipping, so the episode is never completely empty.
            template = _MINIMAL_SEGMENT_TEMPLATE.get(lang, _MINIMAL_SEGMENT_TEMPLATE["en"])
            bio_text = template.format(name=name_raw)

        bio_tts = normalize_for_tts(bio_text, lang=lang, flatten_lines=False)

        # Each segment: first line = saint name (wrapped in <emphasis> by audio_generator),
        # remaining lines = biography body
        segment = name_tts + "\n" + bio_tts
        segments.append(segment)
        saint_names.append(name_tts)

    if not segments:
        raise ValueError(f"No saints found or parsed for {lang} on {date}")

    # Build episode title
    date_str = _format_date(date, lang)
    page_title = cfg["page_title"]
    episode_title = f"{page_title} - {date_str}"

    return episode_title, segments
