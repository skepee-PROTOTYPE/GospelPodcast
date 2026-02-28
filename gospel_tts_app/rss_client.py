import feedparser
from gospel.text_normalizer import normalize_for_tts

class RSSClient:
    def __init__(self, feed_url: str):
        self.feed_url = feed_url

    def _parse_entry(self, entry):
        title = normalize_for_tts(entry.get('title', ''), feed_url=self.feed_url, flatten_lines=False)
        summary_raw = entry.get('summary') or entry.get('description') or ''
        summary = normalize_for_tts(summary_raw, feed_url=self.feed_url, flatten_lines=False)
        # RFC 2822 pub_date from RSS, fallback to empty string
        pub_date = entry.get('published', '')
        link = entry.get('link', '')
        return {"title": title, "summary": summary, "pub_date": pub_date, "link": link}

    def fetch_latest(self):
        feed = feedparser.parse(self.feed_url)
        if not feed or not feed.entries:
            return None
        return self._parse_entry(feed.entries[0])

    def fetch_all(self):
        """Return all available entries from the RSS feed, newest first."""
        feed = feedparser.parse(self.feed_url)
        if not feed or not feed.entries:
            return []
        return [self._parse_entry(e) for e in feed.entries]
