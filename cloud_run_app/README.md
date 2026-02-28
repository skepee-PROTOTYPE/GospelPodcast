# Cloud Run Deployment

This app publishes a daily Gospel audio per language and updates the RSS feed in Firebase Storage.

## Prerequisites
- Google Cloud project + Firebase enabled
- Grant Cloud Run service account access to Storage (`roles/storage.admin` or limited write)
- Set `FIREBASE_BUCKET` to your Firebase Storage bucket name

## Build & Deploy (gcloud)

```bash
# From repo root
gcloud auth login
gcloud config set project <YOUR_GCP_PROJECT>

# Build image in Artifact Registry (or use Cloud Build)
gcloud builds submit --tag gcr.io/<YOUR_GCP_PROJECT>/gospel-tts

# Deploy to Cloud Run
gcloud run deploy gospel-tts \
  --image gcr.io/<YOUR_GCP_PROJECT>/gospel-tts \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars FIREBASE_BUCKET=<YOUR-FIREBASE-BUCKET>,TZ=Europe/Rome

# Test
curl -X POST "https://gospel-tts-<hash>-ew1.a.run.app/publish?lang=it"
```

## Cloud Scheduler (06:00 Europe/Rome)

```bash
# Create a job that hits the Cloud Run URL daily at 06:00 CET
CLOUD_RUN_URL="https://gospel-tts-<hash>-ew1.a.run.app/publish?lang=it"
gcloud scheduler jobs create http gospel-tts-it-0600 \
  --schedule="0 6 * * *" \
  --time-zone="Europe/Rome" \
  --uri="$CLOUD_RUN_URL" \
  --http-method=POST

# Repeat for other languages (de, fr, en, pt, es)
```

## Notes
- If you prefer Firebase-only, you can use Hosting + Scheduled Functions, but Cloud Run is better for Python.
- `serviceAccountKey.json` is NOT required; Cloud Run uses default credentials. Bucket name must be set via `FIREBASE_BUCKET`.
