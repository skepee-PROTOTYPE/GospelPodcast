import os
import json
import argparse
import datetime
from typing import Dict
from gospel.gospel_rss_parser import GospelRSSClient
from gospel.gospel_podcast_publisher import GospelPodcastPublisher
from gospel.audio_generator import AudioGenerator

LANG_CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'configs')

def load_config(lang: str) -> Dict:
    cfg_path = os.path.join(LANG_CONFIG_DIR, f"{lang}.json")
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    parser = argparse.ArgumentParser(description='Publish Daily Gospel podcast episode for a language.')
    parser.add_argument('--lang', default='en', help='Language code (en, it, es, fr, pt, de)')
    args = parser.parse_args()

    config = load_config(args.lang)
    feed_url = config.get('feed_url')
    voice_key = config.get('voice_key', f'{args.lang}-female')

    audio_gen = AudioGenerator(voice=voice_key, speed='normal')

    # --- Attempt 1: fetch structured content from the Vatican News HTML page ---
    title = description = pub_date = guid = ""
    episode = None
    try:
        from gospel.html_scraper import VaticanHTMLScraper
        scraper = VaticanHTMLScraper(args.lang)
        title, segments = scraper.fetch_segments()
        episode = audio_gen.create_episode_from_segments(title, segments)
        description = title
        guid = scraper.day_url()
        pub_date = datetime.date.today().strftime("%a, %d %b %Y 00:00:00 +0000")
        print(f"HTML scraper succeeded for {args.lang}: {title}")
    except Exception as scraper_err:
        print(f"HTML scraper failed ({scraper_err}), falling back to RSS feed...")

    # --- Fallback: use the RSS feed description ---
    if episode is None:
        rss_client = GospelRSSClient(feed_url)
        latest = rss_client.fetch_latest()
        if not latest:
            print('No RSS entry found. Check feed_url.')
            return

        title = latest['title']
        description = latest['summary'] or latest['title']
        pub_date = latest.get('published', '')
        guid = latest.get('link', '')

        episode = audio_gen.create_podcast_episode(title, description)

    audio_path = episode['audio_path']

    publisher = GospelPodcastPublisher(os.path.join(LANG_CONFIG_DIR, f"{args.lang}.json"))
    # Restore episode history from the published RSS before adding today's episode.
    publisher.load_existing_feed()
    audio_url = publisher.upload_audio(audio_path)
    if not audio_url:
        print('Failed to upload audio to Firebase. Check serviceAccountKey.json and bucket.')
        return

    file_size = os.path.getsize(audio_path)
    # Remove local MP3 immediately — Firebase copy is the only one needed.
    try:
        os.remove(audio_path)
    except OSError:
        pass

    publisher.add_episode(
        audio_url, title, description,
        duration=int(episode.get('duration', 0)),
        pub_date=pub_date,
        guid=guid,
        file_size=file_size,
    )
    # Keep up to 6 months of history (~180 episodes); delete older MP3s from storage.
    publisher.prune_episodes(max_episodes=180)
    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    if ok:
        print(f"Published episode for {args.lang}: {title}")
        print(f"RSS uploaded to: {publisher.rss_blob_path}")
    else:
        print('RSS upload failed.')

if __name__ == '__main__':
    main()
