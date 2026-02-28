import feedparser
from typing import Dict, Optional
from gospel.text_normalizer import normalize_for_tts

class GospelRSSClient:
    """Fetches and parses Vatican News Daily Gospel RSS feed."""
    def __init__(self, feed_url: str):
        self.feed_url = feed_url

    def fetch_latest(self) -> Optional[Dict[str, str]]:
        """Return the latest entry with title, summary, link, published."""
        try:
            feed = feedparser.parse(self.feed_url)
            if not feed or not feed.entries:
                return None
            entry = feed.entries[0]
            title = normalize_for_tts(entry.get('title', ''), feed_url=self.feed_url, flatten_lines=False)
            summary_raw = entry.get('summary') or entry.get('description') or ''
            summary = normalize_for_tts(summary_raw, feed_url=self.feed_url, flatten_lines=False)
            link = entry.get('link', '')
            published = entry.get('published', '')
            return {
                'title': title,
                'summary': summary,
                'link': link,
                'published': published,
            }
        except Exception:
            return None
