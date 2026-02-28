import feedparser
from gospel.text_normalizer import normalize_for_tts

class RSSClient:
    def __init__(self, feed_url: str):
        self.feed_url = feed_url

    def fetch_latest(self):
        feed = feedparser.parse(self.feed_url)
        if not feed or not feed.entries:
            return None
        entry = feed.entries[0]
        title = normalize_for_tts(entry.get('title', ''), feed_url=self.feed_url, flatten_lines=False)
        summary_raw = entry.get('summary') or entry.get('description') or ''
        summary = normalize_for_tts(summary_raw, feed_url=self.feed_url, flatten_lines=False)
        return {"title": title, "summary": summary}
