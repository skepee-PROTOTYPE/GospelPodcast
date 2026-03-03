import feedparser
from typing import Dict, List, Optional
from gospel.text_normalizer import normalize_for_tts, html_to_plain_text

class GospelRSSClient:
    """Fetches and parses Vatican News Daily Gospel RSS feed."""
    def __init__(self, feed_url: str):
        self.feed_url = feed_url

    def _parse_entry(self, entry) -> Dict[str, str]:
        title = normalize_for_tts(entry.get('title', ''), feed_url=self.feed_url, flatten_lines=False)
        summary_raw = entry.get('summary') or entry.get('description') or ''
        # Use html_to_plain_text (without TTS smoothing) so parentheses are
        # preserved for pope-comment attribution detection in build_liturgy_segments.
        summary = html_to_plain_text(summary_raw)
        link = entry.get('link', '')
        published = entry.get('published', '')
        return {
            'title': title,
            'summary': summary,
            'link': link,
            'published': published,
        }

    def fetch_latest(self) -> Optional[Dict[str, str]]:
        """Return the latest entry with title, summary, link, published."""
        try:
            feed = feedparser.parse(self.feed_url)
            if not feed or not feed.entries:
                return None
            return self._parse_entry(feed.entries[0])
        except Exception:
            return None

    def fetch_all(self) -> List[Dict[str, str]]:
        """Return all available entries from the RSS feed, newest first."""
        try:
            feed = feedparser.parse(self.feed_url)
            if not feed or not feed.entries:
                return []
            return [self._parse_entry(e) for e in feed.entries]
        except Exception:
            return []
