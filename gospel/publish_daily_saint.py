"""Publish the daily Saint of the Day podcast episode for one language.

Usage:
    python -m gospel.publish_daily_saint --lang it
    python -m gospel.publish_daily_saint --lang en
    python -m gospel.publish_daily_saint --lang all
    python -m gospel.publish_daily_saint --lang it,fr,es

The script:
1. Scrapes Vatican News saint-of-the-day HTML page for *lang*.
2. Builds one podcast segment per saint (with full hagiography if available).
3. Synthesises TTS audio via Google Cloud TTS (Neural2 voices).
4. Uploads the MP3 to Firebase Storage and regenerates the RSS feed.
"""

import argparse
import datetime
import json
import os
from typing import Dict, List

from gospel.saint_scraper import fetch_saints
from gospel.gospel_podcast_publisher import GospelPodcastPublisher
from gospel.audio_generator import AudioGenerator

LANG_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs", "saint")
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


def publish_for_language(lang: str) -> bool:
    """Scrape, generate and publish a saint episode for *lang*.

    Returns True on success, False on failure.
    """
    config = load_config(lang)
    voice_key = config.get("voice_key", f"{lang}-IT-Neural2-C")

    audio_gen = AudioGenerator(voice=voice_key, speed="normal")

    # --- Scrape Vatican News saint-of-the-day page ---
    try:
        title, segments = fetch_saints(lang)
        print(f"  [{lang}] Scraped {len(segments)} saint(s): {title}")
    except Exception as e:
        print(f"  [{lang}] ERROR scraping saints: {e}")
        return False

    if not segments:
        print(f"  [{lang}] No segments produced — skipping.")
        return False

    # --- Synthesise audio ---
    try:
        episode = audio_gen.create_episode_from_segments(title, segments)
    except Exception as e:
        print(f"  [{lang}] ERROR generating audio: {e}")
        return False

    audio_path = episode["audio_path"]

    # --- Publish to Firebase ---
    publisher = GospelPodcastPublisher(
        os.path.join(LANG_CONFIG_DIR, f"{lang}.json")
    )
    publisher.load_existing_feed()

    audio_url = publisher.upload_audio(audio_path)
    if not audio_url:
        print(f"  [{lang}] ERROR: audio upload to Firebase failed.")
        try:
            os.remove(audio_path)
        except OSError:
            pass
        return False

    file_size = os.path.getsize(audio_path)
    try:
        os.remove(audio_path)
    except OSError:
        pass

    today = datetime.date.today()
    pub_date = today.strftime("%a, %d %b %Y 00:00:00 +0000")
    guid = f"saint-{lang}-{today.isoformat()}"

    publisher.add_episode(
        audio_url,
        title,
        title,  # description == title for saints
        duration=int(episode.get("duration", 0)),
        pub_date=pub_date,
        guid=guid,
        file_size=file_size,
    )
    # Keep up to 6 months of history (~180 episodes)
    publisher.prune_episodes(max_episodes=180)

    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    if ok:
        print(f"  [{lang}] Published: {title}")
        print(f"  [{lang}] RSS: {publisher.rss_blob_path}")
    else:
        print(f"  [{lang}] ERROR: RSS upload failed.")
    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Publish daily Saint of the Day podcast episode."
    )
    parser.add_argument(
        "--lang",
        default="it",
        help=(
            "Language code(s): it | en | fr | es | pt | de | all "
            "or comma-separated list (default: it)"
        ),
    )
    args = parser.parse_args()

    try:
        langs = parse_langs(args.lang)
    except ValueError as e:
        parser.error(str(e))
        return

    print(f"Publishing Saint of the Day for: {', '.join(langs)}")
    results = {}
    for lang in langs:
        print(f"\n--- {lang.upper()} ---")
        results[lang] = publish_for_language(lang)

    print("\n=== Summary ===")
    for lang, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  [{status}] {lang}")


if __name__ == "__main__":
    main()
