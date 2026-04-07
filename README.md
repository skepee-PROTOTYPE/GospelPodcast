# ??? Gospel Podcast

Automated multilingual daily Gospel podcast on **Spotify**, powered by Cloud Run and Firebase Storage. Runs daily at **06:00 Rome time**.

## ?? Podcasts

| Language | Spotify | RSS |
|----------|---------|-----|
| ???? Italiano | [Listen](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/it/podcast_feed.xml) |
| ???? English | [Listen](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/en/podcast_feed.xml) |
| ???? Deutsch | [Listen](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/de/podcast_feed.xml) |
| ???? Fran�ais | [Listen](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/fr/podcast_feed.xml) |
| ???? Espa�ol | [Listen](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/es/podcast_feed.xml) |
| ???? Portugu�s | [Listen](https://open.spotify.com/show/4kmH3RcGbb3HIcAs4vTFMJ) | [RSS](https://storage.googleapis.com/gospelpodcast-87c74.firebasestorage.app/gospel/pt/podcast_feed.xml) |

## ?? Deploy

Requires Google Cloud CLI (authenticated), a GCP project with billing, and Firebase Storage.

```powershell
.\deploy.ps1 `
  -ProjectId    "your-gcp-project-id" `
  -Bucket       "your-project.firebasestorage.app" `
  -PodcastEmail "your@email.com" `
  -TtsProvider  "edge"
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ping` | GET | Health check |
| `/publish?lang=it` | POST | Publish today's episode (one language) |
| `/publish-all` | POST | Publish all 6 languages |
| `/publish-history?lang=it` | POST | Backfill all available Vatican News entries |

## Bulk Backfill (local)

```powershell
python -m gospel.publish_all_gospel            # all languages
python -m gospel.publish_all_gospel --langs en,it
```

## Notes

- **Retention**: rolling 180 episodes (~6 months) per language; expired MP3s deleted automatically.
- **Audio**: Date ? Psalm ? Gospel ? Pope comment, with 2.5 s silence between sections.
- **Config**: `gospel/configs/{lang}.json`; Cloud Run env vars `FIREBASE_BUCKET`, `PODCAST_EMAIL`, `TTS_PROVIDER`.
- **Cost tip**: set `TTS_PROVIDER=edge` to avoid paid Google Cloud Text-to-Speech charges.

## License

MIT
