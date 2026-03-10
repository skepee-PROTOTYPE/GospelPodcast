"""Generate and publish podcast episodes for every day of a given month.

Usage:
    python -m gospel.republish_month                     # current month, all langs
    python -m gospel.republish_month --year 2026 --month 3
    python -m gospel.republish_month --langs it,en       # subset of languages

For each (date, language) pair the script:
  1. Fetches liturgy segments from the Vatican News HTML page (html_scraper).
  2. Generates audio via AudioGenerator.
  3. Uploads audio + updates the RSS feed on Firebase.
     If Firebase upload fails (e.g. permission error) the MP3 stays in gospel/out/
     and the run continues with the next entry.
"""

import argparse
import datetime
import json
import os
from typing import Dict, List

from gospel.audio_generator import AudioGenerator
from gospel.gospel_podcast_publisher import GospelPodcastPublisher
from gospel.html_scraper import VaticanHTMLScraper

LANG_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
SUPPORTED_LANGS = ["de", "en", "es", "fr", "it", "pt"]


def load_config(lang: str) -> Dict:
    cfg_path = os.path.join(LANG_CONFIG_DIR, f"{lang}.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_langs(value: str) -> List[str]:
    if value.lower() == "all":
        return SUPPORTED_LANGS
    langs = [x.strip().lower() for x in value.split(",") if x.strip()]
    invalid = [x for x in langs if x not in SUPPORTED_LANGS]
    if invalid:
        raise ValueError(f"Unsupported languages: {', '.join(invalid)}")
    return langs


def days_in_month(year: int, month: int) -> List[datetime.date]:
    """Return every date from day 1 up to min(today, last day of month)."""
    today = datetime.date.today()
    d = datetime.date(year, month, 1)
    dates = []
    while d.month == month and d <= today:
        dates.append(d)
        d += datetime.timedelta(days=1)
    return dates


def publish_day(lang: str, date: datetime.date) -> str:
    """
    Fetch, generate, and publish a single (lang, date) episode.
    Returns a short status string: "OK", "SKIP:reason", or "FAIL:reason".
    """
    config = load_config(lang)
    voice_key = config.get("voice_key", f"{lang}-female")
    audio_gen = AudioGenerator(voice=voice_key, speed="normal")

    # --- Fetch segments from Vatican News HTML ---
    try:
        scraper = VaticanHTMLScraper(lang)
        title, segments = scraper.fetch_segments(date)
        guid = scraper.day_url(date)
        pub_date = date.strftime("%a, %d %b %Y 00:00:00 +0000")
    except Exception as e:
        return f"FAIL:scraper:{e}"

    if not segments:
        return "SKIP:no segments"

    # --- Generate audio ---
    try:
        episode = audio_gen.create_episode_from_segments(title, segments)
    except Exception as e:
        return f"FAIL:audio:{e}"

    audio_path = episode["audio_path"]

    # --- Upload to Firebase and update RSS ---
    try:
        publisher = GospelPodcastPublisher(os.path.join(LANG_CONFIG_DIR, f"{lang}.json"))
        publisher.load_existing_feed()

        audio_url = publisher.upload_audio(audio_path)
        if not audio_url:
            return f"FAIL:firebase_upload (MP3 kept at {audio_path})"

        file_size = os.path.getsize(audio_path)
        try:
            os.remove(audio_path)
        except OSError:
            pass

        publisher.add_episode(
            audio_url,
            title,
            title,  # description = title (HTML scraper doesn't return a summary)
            duration=int(episode.get("duration", 0)),
            pub_date=pub_date,
            guid=guid,
            file_size=file_size,
        )
        publisher.prune_episodes(max_episodes=180)
        rss_local = publisher.generate_rss()
        publisher.upload_rss(rss_local)
        return f"OK:{audio_url}"

    except Exception as e:
        return f"FAIL:firebase:{e} (MP3 kept at {audio_path})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Republish a full month of gospel episodes.")
    parser.add_argument("--year",  type=int, default=datetime.date.today().year)
    parser.add_argument("--month", type=int, default=datetime.date.today().month)
    parser.add_argument("--langs", default="all", help="Comma-separated or 'all'")
    args = parser.parse_args()

    langs = parse_langs(args.langs)
    dates = days_in_month(args.year, args.month)

    if not dates:
        print("No dates to process (month may be in the future).")
        return

    print(f"Republishing {args.year}-{args.month:02d}  "
          f"({len(dates)} days × {len(langs)} languages = {len(dates)*len(langs)} episodes)")

    results: List[tuple] = []
    for date in dates:
        for lang in langs:
            label = f"[{date}][{lang}]"
            print(f"\n{label} Processing...", flush=True)
            status = publish_day(lang, date)
            results.append((date, lang, status))
            print(f"{label} {status}", flush=True)

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    ok     = [(d, l, s) for d, l, s in results if s.startswith("OK")]
    skip   = [(d, l, s) for d, l, s in results if s.startswith("SKIP")]
    failed = [(d, l, s) for d, l, s in results if s.startswith("FAIL")]

    print(f"  OK    : {len(ok)}")
    print(f"  SKIP  : {len(skip)}")
    print(f"  FAILED: {len(failed)}")

    if failed:
        print("\nFailed entries:")
        for d, l, s in failed:
            print(f"  {d} [{l}] {s}")


if __name__ == "__main__":
    main()
