"""Verify that published podcast feeds are live and up to date.

Stdlib only, so it runs both inside Cloud Run (post-publish check) and in the
GitHub Actions daily check without installing the project's dependencies.

CLI:  python -m gospel.feed_check            # checks every gospel/configs/*.json feed
Exit code 1 if any feed is stale or its newest audio file is unreachable.
"""
import datetime
import email.utils
import glob
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

MIN_AUDIO_BYTES = 100_000   # a real episode is ~1 MB; anything this small is broken
_UA = {"User-Agent": "GospelPodcast-feed-check/1.0", "Cache-Control": "no-cache"}
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")


def _request(url: str, method: str = "GET", timeout: int = 30):
    req = urllib.request.Request(url, method=method, headers=_UA)
    return urllib.request.urlopen(req, timeout=timeout)


def check_feed(rss_url: str, expected_guid: Optional[str] = None,
               now: Optional[datetime.datetime] = None) -> List[str]:
    """Return a list of problems with the feed at *rss_url* (empty list = OK).

    With *expected_guid* the newest item must have that guid (used right after
    publishing). Otherwise the newest item must be from today (UTC); a 3-hour
    margin before midnight tolerates pubDates written in Rome local time.
    """
    try:
        with _request(rss_url) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        return [f"cannot fetch/parse RSS: {e}"]

    item = root.find("channel/item")
    if item is None:
        return ["feed has no episodes"]

    problems = []
    guid = (item.findtext("guid") or "").strip()
    pub_text = (item.findtext("pubDate") or "").strip()

    if expected_guid is not None:
        if guid != expected_guid:
            problems.append(f"newest episode guid is {guid!r}, expected {expected_guid!r}")
    else:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        midnight = datetime.datetime.combine(now.astimezone(datetime.timezone.utc).date(),
                                             datetime.time(), datetime.timezone.utc)
        cutoff = midnight - datetime.timedelta(hours=3)
        try:
            published = email.utils.parsedate_to_datetime(pub_text)
            if published.tzinfo is None:
                published = published.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            published = None
        if published is None:
            problems.append(f"newest episode has unparseable pubDate {pub_text!r}")
        elif published < cutoff:
            problems.append(f"newest episode is stale (pubDate {pub_text})")

    enclosure = item.find("enclosure")
    audio_url = enclosure.get("url", "") if enclosure is not None else ""
    if not audio_url:
        problems.append("newest episode has no audio enclosure")
        return problems
    # Check the storage file directly so the daily check isn't counted as a
    # listen in OP3 stats.
    if audio_url.startswith("https://op3.dev/e/"):
        audio_url = audio_url[len("https://op3.dev/e/"):]
        if not audio_url.startswith(("http://", "https://")):
            audio_url = "https://" + audio_url
    try:
        with _request(audio_url, method="HEAD") as resp:
            size = int(resp.headers.get("Content-Length") or 0)
        if size < MIN_AUDIO_BYTES:
            problems.append(f"audio too small ({size} bytes): {audio_url}")
    except Exception as e:
        problems.append(f"audio unreachable ({e}): {audio_url}")
    return problems


def main() -> int:
    failed = False
    for cfg_path in sorted(glob.glob(os.path.join(CONFIG_DIR, "*.json"))):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        lang = cfg.get("language", os.path.basename(cfg_path))
        rss_url = cfg.get("podcast_info", {}).get("rss_url")
        if not rss_url:
            print(f"[{lang}] FAIL: no rss_url in {cfg_path}")
            failed = True
            continue
        problems = check_feed(rss_url)
        if problems:
            failed = True
            for p in problems:
                print(f"[{lang}] FAIL: {p}")
        else:
            print(f"[{lang}] OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
