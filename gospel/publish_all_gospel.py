"""Publish ALL available Vatican News RSS entries for one or more languages.

Usage:
    python -m gospel.publish_all_gospel              # all 6 languages
    python -m gospel.publish_all_gospel --langs en,it

For each language the script:
  1. Loads the existing published RSS from Firebase (episode history).
  2. Fetches every entry currently available in the Vatican News feed.
  3. Skips entries whose title is already in the published history.
  4. Generates audio and uploads to Firebase for each new entry (oldest first).
  5. Prunes to the 6-month cap (180 episodes) and re-uploads the RSS.

The Vatican News RSS typically carries ~10-14 days of entries.
"""

import argparse
import json
import os
from typing import Dict, List

from gospel.audio_generator import AudioGenerator
from gospel.gospel_podcast_publisher import GospelPodcastPublisher
from gospel.gospel_rss_parser import GospelRSSClient

LANG_CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'configs')
SUPPORTED_LANGS = ["de", "en", "es", "fr", "it", "pt"]


def load_config(lang: str) -> Dict:
    cfg_path = os.path.join(LANG_CONFIG_DIR, f"{lang}.json")
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _normalise_title(title: str) -> str:
    """Lowercase + strip for deduplication comparison."""
    return (title or "").lower().strip()


def publish_all_for_lang(lang: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Language: {lang.upper()}")
    print(f"{'='*60}")

    config = load_config(lang)
    feed_url = config.get('feed_url', '')
    if not feed_url or 'TODO' in feed_url:
        print(f"  SKIP: no feed_url in config.")
        return

    voice_key = config.get('voice_key', f'{lang}-female')

    # --- Load existing published history ---
    publisher = GospelPodcastPublisher(os.path.join(LANG_CONFIG_DIR, f"{lang}.json"))
    publisher.load_existing_feed()
    existing_titles = {_normalise_title(ep['title']) for ep in publisher.episodes}
    existing_guids  = {ep['guid'] for ep in publisher.episodes}
    print(f"  Existing history: {len(publisher.episodes)} episodes")

    # --- Fetch all available entries from Vatican News RSS ---
    rss_client = GospelRSSClient(feed_url)
    all_entries = rss_client.fetch_all()
    if not all_entries:
        print(f"  No entries found in Vatican News RSS. Check feed_url.")
        return
    print(f"  Vatican News RSS entries available: {len(all_entries)}")

    # --- Filter out already-published entries ---
    new_entries: List[Dict] = []
    for entry in all_entries:
        title_norm = _normalise_title(entry.get('title', ''))
        link = entry.get('link', '')
        if title_norm in existing_titles or (link and link in existing_guids):
            print(f"  SKIP (already published): {entry.get('title', '')[:70]}")
        else:
            new_entries.append(entry)

    if not new_entries:
        print(f"  All entries already published. Nothing to do.")
        return

    print(f"  New entries to publish: {len(new_entries)}")

    # --- Generate audio and publish each new entry, oldest first ---
    audio_gen = AudioGenerator(voice=voice_key, speed='normal')
    published_count = 0

    for entry in reversed(new_entries):   # reversed → oldest first
        title       = entry.get('title', '')
        description = entry.get('summary') or title
        link        = entry.get('link', '')
        pub_date    = entry.get('published', '')

        print(f"\n  [{lang}] Publishing: {title[:70]}")
        try:
            episode   = audio_gen.create_podcast_episode(title, description)
            audio_path = episode['audio_path']

            audio_url = publisher.upload_audio(audio_path)
            try:
                file_size = os.path.getsize(audio_path)
                os.remove(audio_path)
            except OSError:
                file_size = 0

            if not audio_url:
                print(f"    ERROR: audio upload failed.")
                continue

            publisher.add_episode(
                audio_url,
                title,
                description,
                duration=int(episode.get('duration', 0)),
                pub_date=pub_date,
                guid=link or '',   # use Vatican News URL as stable guid
                file_size=file_size,
            )
            published_count += 1
            print(f"    OK: {audio_url}")

        except Exception as exc:
            print(f"    ERROR: {exc}")

    if published_count == 0:
        print(f"\n  No new episodes were successfully published for {lang}.")
        return

    # --- Prune to 6-month cap and upload RSS ---
    publisher.prune_episodes(max_episodes=180)
    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    if ok:
        print(f"\n  RSS uploaded ({len(publisher.episodes)} total episodes): {publisher.rss_blob_path}")
    else:
        print(f"\n  ERROR: RSS upload failed for {lang}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Publish all available Vatican News entries for one or more languages.'
    )
    parser.add_argument(
        '--langs',
        default='all',
        help='Comma-separated language codes (de,en,es,fr,it,pt) or "all"',
    )
    args = parser.parse_args()

    if args.langs.lower() == 'all':
        langs = SUPPORTED_LANGS
    else:
        langs = [x.strip().lower() for x in args.langs.split(',') if x.strip()]
        invalid = [x for x in langs if x not in SUPPORTED_LANGS]
        if invalid:
            print(f"Unsupported languages: {', '.join(invalid)}")
            raise SystemExit(1)

    for lang in langs:
        try:
            publish_all_for_lang(lang)
        except Exception as exc:
            print(f"\n  FATAL ERROR for {lang}: {exc}")

    print("\nDone.")


if __name__ == '__main__':
    main()
