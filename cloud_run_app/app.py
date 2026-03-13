import datetime
import json
import logging
import os
import sys
from typing import Dict, Optional, Tuple

from flask import Flask, request, jsonify

# Ensure repo root is on path when running locally
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gospel_tts_app.feeds import FEED_URLS
from gospel_tts_app.rss_client import RSSClient
from gospel.audio_generator import AudioGenerator
from gospel.gospel_podcast_publisher import GospelPodcastPublisher
from gospel.html_scraper import VaticanHTMLScraper
from gospel.saint_scraper import fetch_saints, _LANG_CFG as SAINT_LANGS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'gospel', 'configs')
SAINT_CONFIG_DIR = os.path.join(BASE_DIR, 'gospel', 'configs', 'saint')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_voice(lang: str) -> str:
    """Return the Neural2 voice key for *lang* from its config file."""
    cfg_path = os.path.join(CONFIG_DIR, f"{lang}.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f).get("voice_key", lang)
    except Exception:
        return lang  # falls back to _VOICES[lang] inside AudioGenerator


# ── core publish logic ────────────────────────────────────────────────────────

def _do_publish(lang: str, force: bool = False) -> Tuple[Dict, int]:
    """Generate audio + update Firebase RSS for one language.

    Tries the Vatican News HTML scraper first (clean section structure), then
    falls back to the RSS feed description when the scraper fails.

    When *force* is True the idempotency check is skipped, allowing today's
    episode to be regenerated even if it was already published.

    Returns (result_dict, http_status_code).
    """
    if lang not in FEED_URLS:
        return {"error": f"unsupported lang: {lang}"}, 400

    cfg_path = os.path.join(CONFIG_DIR, f"{lang}.json")
    publisher = GospelPodcastPublisher(cfg_path)
    publisher.load_existing_feed()

    audio_gen = AudioGenerator(voice=_load_voice(lang), speed='normal')

    title = description = pub_date = guid = ""
    segments: Optional[list] = None

    # --- Attempt 1: Vatican News HTML scraper (best structural quality) ---
    try:
        scraper = VaticanHTMLScraper(lang)
        title, segments = scraper.fetch_segments()
        guid = scraper.day_url()
        pub_date = datetime.date.today().strftime("%a, %d %b %Y 00:00:00 +0000")
        description = title
        logger.info("[%s] HTML scraper succeeded: %s", lang, title)
    except Exception as scraper_err:
        logger.warning("[%s] HTML scraper failed (%s), falling back to RSS", lang, scraper_err)

    # --- Attempt 2: RSS feed fallback ---
    if not title:
        rss = RSSClient(FEED_URLS[lang])
        latest = rss.fetch_latest()
        if not latest:
            return {"error": "no rss entry"}, 404
        title = latest['title']
        description = latest['summary'] or title
        pub_date = latest.get('pub_date', '')
        guid = latest.get('link', '')

    def _cleanup(*paths):
        for p in paths:
            try:
                os.remove(p)
            except Exception:
                pass

    # Skip if today's episode is already in the feed (idempotent re-runs)
    if not force:
        existing_guids = {ep['guid'] for ep in publisher.episodes}
        existing_titles = {(ep['title'] or '').lower().strip() for ep in publisher.episodes}
        if (guid and guid in existing_guids) or title.lower().strip() in existing_titles:
            logger.info("[%s] already published: %s", lang, title)
            return {"lang": lang, "title": title, "skipped": True, "rss": publisher.rss_blob_path}, 200

    # Generate audio (use structured segments from scraper when available)
    if segments is not None:
        episode = audio_gen.create_episode_from_segments(title, segments)
    else:
        episode = audio_gen.create_podcast_episode(title, description)
    audio_path = episode['audio_path']

    audio_url = publisher.upload_audio(audio_path)
    if not audio_url:
        _cleanup(audio_path)
        return {"error": "audio upload failed"}, 500

    publisher.add_episode(audio_url, title, description,
                          duration=int(episode.get('duration', 0) or 0),
                          pub_date=pub_date,
                          guid=guid)
    publisher.prune_episodes(max_episodes=180)
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
    audio_gen = AudioGenerator(voice=_load_voice(lang), speed='normal')

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
    """Publish one language episode. Query params: ?lang=<code>[&force=1]"""
    lang = request.args.get('lang', 'it')
    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    result, status = _do_publish(lang, force=force)
    return jsonify(result), status


@app.post('/publish-all')
def publish_all():
    """Publish all supported languages sequentially and return a per-language summary.

    A 207 Multi-Status is returned if any language fails so Cloud Scheduler
    treats the job as failed and can alert/retry.
    Query param: ?force=1 to regenerate even if already published today.
    """
    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    results = {}
    for lang in FEED_URLS:
        result, status = _do_publish(lang, force=force)
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


# ── saint publish logic ───────────────────────────────────────────────────────

def _do_publish_saint(lang: str) -> Tuple[Dict, int]:
    """Scrape Vatican News Saint of the Day, generate audio and publish for *lang*.

    Returns (result_dict, http_status_code).
    """
    if lang not in SAINT_LANGS:
        return {"error": f"unsupported saint lang: {lang}"}, 400

    import json
    cfg_path = os.path.join(SAINT_CONFIG_DIR, f"{lang}.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        return {"error": f"saint config not found: {cfg_path}"}, 500

    voice_key = config.get("voice_key", f"{lang}-IT-Neural2-C")
    audio_gen = AudioGenerator(voice=voice_key, speed="normal")

    # Scrape Vatican News
    try:
        title, segments = fetch_saints(lang)
        logger.info("[saint/%s] scraped %d saint(s): %s", lang, len(segments), title)
    except Exception as e:
        logger.error("[saint/%s] scrape error: %s", lang, e)
        return {"error": f"scrape failed: {e}"}, 502

    if not segments:
        return {"error": "no segments produced"}, 404

    # Skip if already published today (idempotent re-runs)
    publisher = GospelPodcastPublisher(cfg_path)
    publisher.load_existing_feed()
    today = datetime.date.today()
    guid = f"saint-{lang}-{today.isoformat()}"
    existing_guids = {ep["guid"] for ep in publisher.episodes}
    if guid in existing_guids:
        logger.info("[saint/%s] already published: %s", lang, title)
        return {"lang": lang, "title": title, "skipped": True, "rss": publisher.rss_blob_path}, 200

    # Generate audio
    try:
        episode = audio_gen.create_episode_from_segments(title, segments)
    except Exception as e:
        logger.error("[saint/%s] audio generation error: %s", lang, e)
        return {"error": f"audio generation failed: {e}"}, 500

    audio_path = episode["audio_path"]

    def _cleanup(*paths):
        for p in paths:
            try:
                os.remove(p)
            except Exception:
                pass

    audio_url = publisher.upload_audio(audio_path)
    if not audio_url:
        _cleanup(audio_path)
        return {"error": "audio upload failed"}, 500

    file_size = os.path.getsize(audio_path)
    _cleanup(audio_path)

    pub_date = today.strftime("%a, %d %b %Y 00:00:00 +0000")
    publisher.add_episode(
        audio_url, title, title,
        duration=int(episode.get("duration", 0)),
        pub_date=pub_date,
        guid=guid,
        file_size=file_size,
    )
    publisher.prune_episodes(max_episodes=180)
    rss_local = publisher.generate_rss()
    ok = publisher.upload_rss(rss_local)
    _cleanup(rss_local)

    if not ok:
        return {"error": "rss upload failed"}, 500

    logger.info("[saint/%s] published: %s", lang, title)
    return {"lang": lang, "title": title, "audio_url": audio_url, "rss": publisher.rss_blob_path}, 200


@app.post('/publish-saint')
def publish_saint():
    """Publish Saint of the Day for one language. Query param: ?lang=<code>"""
    lang = request.args.get('lang', 'it')
    result, status = _do_publish_saint(lang)
    return jsonify(result), status


@app.post('/publish-saint-all')
def publish_saint_all():
    """Publish Saint of the Day for all supported languages sequentially."""
    results = {}
    for lang in SAINT_LANGS:
        result, status = _do_publish_saint(lang)
        results[lang] = {"status": status, "detail": result}
    overall = 200 if all(v["status"] == 200 for v in results.values()) else 207
    return jsonify(results), overall


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
