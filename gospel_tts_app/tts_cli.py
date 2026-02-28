import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from feeds import FEED_URLS
from rss_client import RSSClient
from audio_generator import synthesize
from gospel.text_normalizer import build_italian_liturgy_segments


def main():
    parser = argparse.ArgumentParser(description="Generate Gospel TTS audio from RSS or text")
    parser.add_argument("--lang", default="it", help="Language: it, en, es, fr, pt, de")
    parser.add_argument("--text", default=None, help="Custom text (skip RSS)")
    parser.add_argument("--out", default=None, help="Output MP3 path")
    parser.add_argument("--speed", default="normal", choices=["normal", "slow"], help="Speaking rate")
    args = parser.parse_args()

    if args.text:
        title = f"Vangelo del giorno"
        description = args.text
        segments = None
    else:
        feed_url = FEED_URLS.get(args.lang)
        if not feed_url:
            print("Unsupported lang or missing feed URL.")
            return
        rss = RSSClient(feed_url)
        latest = rss.fetch_latest()
        if not latest:
            print("No RSS entry found.")
            return
        title = latest["title"]
        description = latest["summary"] or latest["title"]
        segments = build_italian_liturgy_segments(description) if args.lang == "it" else None

    text = f"{title}\n{description}"
    out_path = synthesize(
        text,
        lang=args.lang,
        speed=args.speed,
        out_dir=None,
        segments=segments,
        pause_seconds=5 if args.lang == "it" and segments and len(segments) > 1 else 0,
    )

    if args.out:
        import os
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(out_path, "rb") as src, open(args.out, "wb") as dst:
            dst.write(src.read())
        out_path = args.out

    print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()
