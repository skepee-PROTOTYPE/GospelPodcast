import os
import json
import argparse
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

    rss_client = GospelRSSClient(feed_url)
    latest = rss_client.fetch_latest()
    if not latest:
        print('No RSS entry found. Check feed_url.')
        return

    title = latest['title']
    description = latest['summary'] or latest['title']

    audio_gen = AudioGenerator(voice=voice_key, speed='normal')
    episode = audio_gen.create_podcast_episode(title, description)
    audio_path = episode['audio_path']

    publisher = GospelPodcastPublisher(os.path.join(LANG_CONFIG_DIR, f"{args.lang}.json"))
    audio_url = publisher.upload_audio(audio_path)
    if not audio_url:
        print('Failed to upload audio to Firebase. Check serviceAccountKey.json and bucket.')
        return

    publisher.add_episode(audio_url, title, description, duration=int(episode.get('duration', 0)))
    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    if ok:
        print(f"Published episode for {args.lang}: {title}")
        print(f"RSS uploaded to: {publisher.rss_blob_path}")
    else:
        print('RSS upload failed.')

if __name__ == '__main__':
    main()
