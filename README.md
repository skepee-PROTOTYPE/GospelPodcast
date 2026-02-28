# 🎙️ Gospel Podcast

A fully automated, multilingual daily Gospel podcast published to **Spotify** — powered by **Google Cloud Run**, **Firebase Storage**, and **gTTS** (text-to-speech).

Every morning at **06:00 Rome time**, the system automatically:
1. Fetches the daily Gospel reading from Vatican News RSS feeds
2. Converts it to audio using text-to-speech
3. Uploads the MP3 and updates the RSS feed on Firebase Storage
4. Spotify polls the RSS and publishes the new episode automatically 🎧

---

## 🌍 Available Podcasts

| Language | Podcast | RSS Feed |
|----------|---------|----------|
| 🇮🇹 Italiano | [Listen on Spotify](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/it/podcast_feed.xml) |
| 🇬🇧 English | [Listen on Spotify](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/en/podcast_feed.xml) |
| 🇩🇪 Deutsch | [Listen on Spotify](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/de/podcast_feed.xml) |
| 🇫🇷 Français | [Listen on Spotify](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/fr/podcast_feed.xml) |
| 🇪🇸 Español | [Listen on Spotify](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/es/podcast_feed.xml) |
| 🇵🇹 Português | [Listen on Spotify](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/pt/podcast_feed.xml) |

---

## 🏗️ Architecture

```
Vatican News RSS
      │
      ▼
Cloud Scheduler ──── daily 06:00 Rome time (one job per language, 2-min stagger)
      │  POST /publish?lang=XX
      ▼
Cloud Run  (Flask · gospel-tts · europe-west1)
      │
      ├── Vatican News RSS → parse latest Gospel entry
      ├── gTTS → generate MP3 audio
      │
      └── Firebase Storage  (gospelpodcast-87c74.firebasestorage.app)
              ├── gospel/{lang}/podcast_audio/*.mp3   ← episode audio
              └── gospel/{lang}/podcast_feed.xml      ← RSS feed
                          │
                          ▼
                    Spotify polls RSS feed
                          │
                          ▼
                   Episode published 🎧
```

---

## 📁 Project Structure

```
GospelPodcast/
├── cloud_run_app/                   # Flask app deployed on Cloud Run
│   ├── app.py                       #   GET  /ping
│   │                                #   POST /publish?lang=XX
│   │                                #   POST /publish-all
│   ├── Dockerfile
│   └── requirements.txt
├── gospel/
│   ├── configs/                     # Per-language JSON configs
│   │   ├── it.json  🇮🇹
│   │   ├── en.json  🇬🇧
│   │   ├── de.json  🇩🇪
│   │   ├── fr.json  🇫🇷
│   │   ├── es.json  🇪🇸
│   │   └── pt.json  🇵🇹
│   ├── gospel_podcast_publisher.py  # Firebase upload + RSS generation
│   ├── audio_generator.py           # gTTS wrapper
│   ├── gospel_rss_parser.py         # Vatican News RSS parser
│   └── text_normalizer.py
├── gospel_tts_app/                  # Shared RSS client + feed URL map
├── cloudbuild.yaml                  # Cloud Build config (builds Docker image)
├── deploy.ps1                       # One-shot deploy (Cloud Run + Scheduler)
├── firebase.json                    # Firebase project config
├── storage.rules                    # Firebase Storage public-read rules
└── .gcloudignore                    # Excludes .venv, covers, caches from build
```

---

## 🚀 Deploy Your Own

### Prerequisites
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) — authenticated
- A **GCP project** with billing enabled
- A **Firebase project** (same GCP project) with Storage enabled

### One-shot deploy (PowerShell)

```powershell
.\deploy.ps1 `
  -ProjectId    "your-gcp-project-id" `
  -Bucket       "your-project.firebasestorage.app" `
  -PodcastEmail "your@email.com"
```

The script will:
1. Enable required GCP APIs
2. Create service accounts with least-privilege IAM roles
3. Build and push the Docker image via Cloud Build
4. Deploy the Flask app to Cloud Run (512 MB, 300 s timeout)
5. Create 6 Cloud Scheduler jobs (daily 06:00–06:10, 2-min stagger per language)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ping` | GET | Health check → `{"status":"ok"}` |
| `/publish?lang=it` | POST | Publish one language episode |
| `/publish-all` | POST | Publish all 6 languages |

---

## ⚙️ Configuration

Each language has a config file in `gospel/configs/{lang}.json`:

```json
{
  "language": "it",
  "feed_url": "https://www.vaticannews.va/it/vangelo-del-giorno-e-parola-del-giorno.rss.xml",
  "bucket_name": "your-project.firebasestorage.app",
  "storage_prefix": "gospel/it",
  "voice_key": "it-female",
  "podcast_info": {
    "title": "Vangelo Quotidiano (Italiano)",
    "author": "Vatican News",
    "description": "Vangelo quotidiano da Vatican News",
    "cover_art": "https://storage.googleapis.com/.../gospel/it/cover.png",
    "rss_url": "https://storage.googleapis.com/.../gospel/it/podcast_feed.xml"
  }
}
```

### Environment Variables (Cloud Run)

Sensitive values are **never stored in the repo** — they are passed as Cloud Run environment variables:

| Variable | Description |
|---|---|
| `FIREBASE_BUCKET` | Firebase Storage bucket name |
| `PODCAST_EMAIL` | Podcast owner email (used in RSS `<itunes:owner>` tag) |

---

## 📜 License

MIT

