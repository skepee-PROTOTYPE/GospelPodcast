import argparse
import json
import os
import re
from datetime import datetime
from typing import Dict, Iterable, List

from gospel.audio_generator import AudioGenerator
from gospel.gospel_rss_parser import GospelRSSClient

LANG_CONFIG_DIR = os.path.join(os.path.dirname(__file__), 'configs')
SUPPORTED_LANGS = ["de", "en", "es", "fr", "it", "pt"]


def load_config(lang: str) -> Dict:
    cfg = os.path.join(LANG_CONFIG_DIR, f"{lang}.json")
    with open(cfg, 'r', encoding='utf-8') as f:
        return json.load(f)


def slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", (text or "").strip())
    text = re.sub(r"[^a-zA-Z0-9\-]", "", text)
    return text[:60] if text else "episode"


def parse_langs(value: str) -> List[str]:
    if value.lower() == 'all':
        return SUPPORTED_LANGS
    langs = [x.strip().lower() for x in value.split(',') if x.strip()]
    invalid = [x for x in langs if x not in SUPPORTED_LANGS]
    if invalid:
        raise ValueError(f"Unsupported languages: {', '.join(invalid)}")
    return langs


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def copy_file(src: str, dst: str) -> None:
    with open(src, 'rb') as src_fp, open(dst, 'wb') as dst_fp:
        dst_fp.write(src_fp.read())


def generate_for_language(lang: str, out_dir: str, speed: str) -> Dict:
    cfg = load_config(lang)
    feed_url = cfg.get('feed_url')
    if not feed_url or 'TODO' in feed_url:
        return {'lang': lang, 'ok': False, 'error': 'missing feed_url in config'}

    rss = GospelRSSClient(feed_url)
    latest = rss.fetch_latest()
    if not latest:
        return {'lang': lang, 'ok': False, 'error': 'no rss entry found'}

    title = latest.get('title') or f'Daily Gospel {lang.upper()}'
    description = latest.get('summary') or title
    voice_key = cfg.get('voice_key', f'{lang}-female')

    audio_gen = AudioGenerator(voice=voice_key, speed=speed)
    episode = audio_gen.create_podcast_episode(title, description)

    stamp = datetime.now().strftime('%Y%m%d')
    file_name = f"{stamp}_{lang}_{slugify(title)}.mp3"
    target_path = os.path.join(out_dir, file_name)
    copy_file(episode['audio_path'], target_path)

    return {
        'lang': lang,
        'ok': True,
        'title': title,
        'audio_path': target_path,
        'duration': int(episode.get('duration', 0) or 0),
    }


def print_results(results: Iterable[Dict]) -> int:
    failures = 0
    print('\nGeneration summary:')
    for row in results:
        if row.get('ok'):
            print(f"  [OK] {row['lang']}: {row['audio_path']}")
        else:
            failures += 1
            print(f"  [ERR] {row['lang']}: {row.get('error', 'unknown error')}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Generate one MP3 per language for manual Spotify for Creators upload.'
    )
    parser.add_argument(
        '--langs',
        default='all',
        help='Comma-separated languages (de,en,es,fr,it,pt) or all',
    )
    parser.add_argument(
        '--out-dir',
        default=os.path.join(os.path.dirname(__file__), 'out_spotify'),
        help='Directory where generated MP3 files will be copied',
    )
    parser.add_argument(
        '--speed',
        default='normal',
        choices=['slow', 'normal', 'fast'],
        help='Speaking rate for generated audio',
    )
    args = parser.parse_args()

    try:
        langs = parse_langs(args.langs)
    except ValueError as e:
        print(str(e))
        return

    out_dir = ensure_dir(args.out_dir)
    print(f"Generating MP3 files in: {out_dir}")

    rows = []
    for lang in langs:
        rows.append(generate_for_language(lang=lang, out_dir=out_dir, speed=args.speed))

    failures = print_results(rows)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
