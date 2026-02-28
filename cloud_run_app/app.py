import logging
import os
import sys
from typing import Dict, Tuple

from flask import Flask, request, jsonify

# Ensure repo root is on path when running locally
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gospel_tts_app.feeds import FEED_URLS
from gospel_tts_app.rss_client import RSSClient
from gospel.audio_generator import AudioGenerator
from gospel.gospel_podcast_publisher import GospelPodcastPublisher

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'gospel', 'configs')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ── core publish logic ────────────────────────────────────────────────────────

def _do_publish(lang: str) -> Tuple[Dict, int]:
    """Generate audio + update Firebase RSS for one language.

    Returns (result_dict, http_status_code).
    """
    if lang not in FEED_URLS:
        return {"error": f"unsupported lang: {lang}"}, 400

    feed_url = FEED_URLS[lang]
    rss = RSSClient(feed_url)
    latest = rss.fetch_latest()
    if not latest:
        return {"error": "no rss entry"}, 404

    title = latest['title']
    description = latest['summary'] or title

    # Generate MP3 via gTTS
    audio_gen = AudioGenerator(voice=f"{lang}-female", speed='normal')
    episode = audio_gen.create_podcast_episode(title, description)
    audio_path = episode['audio_path']

    # Upload audio to Firebase Storage
    cfg_path = os.path.join(CONFIG_DIR, f"{lang}.json")
    publisher = GospelPodcastPublisher(cfg_path)
    audio_url = publisher.upload_audio(audio_path)

    def _cleanup(*paths):
        for p in paths:
            try:
                os.remove(p)
            except Exception:
                pass

    if not audio_url:
        _cleanup(audio_path)
        return {"error": "audio upload failed"}, 500

    # Rebuild + upload RSS feed
    publisher.add_episode(audio_url, title, description,
                          duration=int(episode.get('duration', 0) or 0),
                          pub_date=latest.get('pub_date', ''),
                          guid=latest.get('link', ''))
    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    _cleanup(audio_path, rss_local)

    if not ok:
        return {"error": "rss upload failed"}, 500

    logger.info("[%s] published: %s", lang, title)
    return {"lang": lang, "title": title, "audio_url": audio_url, "rss": publisher.rss_blob_path}, 200


def _do_publish_history(lang: str) -> Tuple[Dict, int]:
    """Generate audio for ALL available RSS entries and build a full RSS feed."""
    if lang not in FEED_URLS:
        return {"error": f"unsupported lang: {lang}"}, 400

    feed_url = FEED_URLS[lang]
    rss_client = RSSClient(feed_url)
    entries = rss_client.fetch_all()
    if not entries:
        return {"error": "no rss entries"}, 404

    cfg_path = os.path.join(CONFIG_DIR, f"{lang}.json")
    publisher = GospelPodcastPublisher(cfg_path)
    audio_gen = AudioGenerator(voice=f"{lang}-female", speed='normal')

    published = []
    errors = []
    # Process oldest first so RSS feed is in correct chronological order
    for entry in reversed(entries):
        title = entry['title']
        description = entry['summary'] or title
        try:
            episode = audio_gen.create_podcast_episode(title, description)
            audio_path = episode['audio_path']
            audio_url = publisher.upload_audio(audio_path)
            try:
                os.remove(audio_path)
            except Exception:
                pass
            if not audio_url:
                errors.append({"title": title, "error": "audio upload failed"})
                continue
            publisher.add_episode(audio_url, title, description,
                                  duration=int(episode.get('duration', 0) or 0),
                                  pub_date=entry.get('pub_date', ''),
                                  guid=entry.get('link', ''))
            published.append({"title": title, "audio_url": audio_url})
            logger.info("[%s] history: %s", lang, title)
        except Exception as e:
            logger.error("[%s] history error for '%s': %s", lang, title, e)
            errors.append({"title": title, "error": str(e)})

    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    try:
        os.remove(rss_local)
    except Exception:
        pass

    if not ok:
        return {"error": "rss upload failed"}, 500

    return {"lang": lang, "published": len(published), "errors": errors,
            "rss": publisher.rss_blob_path}, 200



def healthz():
    return jsonify({"status": "ok"})


@app.post('/publish')
def publish():
    """Publish one language episode. Query param: ?lang=<code>"""
    lang = request.args.get('lang', 'it')
    result, status = _do_publish(lang)
    return jsonify(result), status


@app.post('/publish-all')
def publish_all():
    """Publish all supported languages sequentially and return a per-language summary.

    A 207 Multi-Status is returned if any language fails so Cloud Scheduler
    treats the job as failed and can alert/retry.
    """
    results = {}
    for lang in FEED_URLS:
        result, status = _do_publish(lang)
        results[lang] = {"status": status, "detail": result}

    overall = 200 if all(v["status"] == 200 for v in results.values()) else 207
    return jsonify(results), overall


@app.post('/publish-history')
def publish_history():
    """Backfill all available RSS entries for one or all languages.
    Query param: ?lang=XX  (omit for all languages)
    """
    lang = request.args.get('lang')
    if lang:
        result, status = _do_publish_history(lang)
        return jsonify(result), status
    # All languages
    results = {}
    for l in FEED_URLS:
        result, status = _do_publish_history(l)
        results[l] = {"status": status, "detail": result}
    overall = 200 if all(v["status"] == 200 for v in results.values()) else 207
    return jsonify(results), overall


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
