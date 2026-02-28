import os
import json
import argparse
from typing import Dict, Optional

from gospel.gospel_rss_parser import GospelRSSClient
from gospel.audio_generator import AudioGenerator

LANG_CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'configs')


def load_config(lang: str) -> Dict:
    cfg = os.path.join(LANG_CONFIG_DIR, f"{lang}.json")
    with open(cfg, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='Generate TTS audio from RSS or text')
    parser.add_argument('--lang', default='it', help='Language code (it, en, es, fr, pt, de)')
    parser.add_argument('--out', default=None, help='Output MP3 path (optional)')
    parser.add_argument('--speed', default='normal', choices=['slow', 'normal', 'fast'], help='Speaking rate')
    parser.add_argument('--text', default=None, help='Override text to synthesize (skip RSS)')
    parser.add_argument('--use-en-feed', action='store_true', help='Fallback to English RSS if selected lang feed is missing')
    args = parser.parse_args()

    voice_key = f"{args.lang}-female"
    audio_gen = AudioGenerator(voice=voice_key, speed=args.speed)

    title = None
    description = None
    if args.text:
        title = f"Sintesi {args.lang.upper()}"
        description = args.text
    else:
        cfg = load_config(args.lang)
        feed_url = cfg.get('feed_url')
        if (not feed_url or 'TODO' in feed_url) and args.use_en_feed:
            feed_url = load_config('en').get('feed_url')
        if not feed_url or 'TODO' in feed_url:
            print('Feed URL missing. Provide --text or set feed_url in configs/<lang>.json.')
            return
        rss = GospelRSSClient(feed_url)
        latest = rss.fetch_latest()
        if not latest:
            print('No RSS entry found. Check feed_url.')
            return
        title = latest['title']
        description = latest['summary'] or latest['title']

    episode = audio_gen.create_podcast_episode(title, description)
    audio_path = episode['audio_path']
    if args.out:
        # Copy to requested path
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(audio_path, 'rb') as src, open(args.out, 'wb') as dst:
            dst.write(src.read())
        audio_path = args.out

    print(f"Generated: {audio_path}")
    print(f"Duration: {episode['duration']}s | Lang: {audio_gen.lang} | Speed: {args.speed}")


if __name__ == '__main__':
    main()
