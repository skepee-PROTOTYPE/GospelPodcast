# ==============================================================================
# GospelPodcast – one-shot deploy script for Cloud Run + Cloud Scheduler
# Usage: .\deploy.ps1
# Requirements: gcloud CLI authenticated, Artifact Registry / GCR enabled
# ==============================================================================

param (
    [string]$ProjectId    = "",
    [string]$Bucket       = "",
    [string]$PodcastEmail = "",
    [string]$Region       = "europe-west1",
    [string]$ServiceName  = "gospel-tts",
    [string]$ScheduleTime = "0 6 * * *",   # 06:00 daily
    [string]$TimeZone     = "Europe/Rome"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── helpers ────────────────────────────────────────────────────────────────────
function Ask([string]$prompt, [string]$default = "") {
    $hint = if ($default) { " [$default]" } else { "" }
    $value = Read-Host "$prompt$hint"
    if (-not $value) { $value = $default }
    return $value
}

function RunOrDie {
    param([string[]]$Parts)
    $display = $Parts -join ' '
    Write-Host "`n> $display" -ForegroundColor Cyan
    if ($Parts.Length -eq 1) {
        & $Parts[0]
    } else {
        $rest = $Parts[1..($Parts.Length - 1)]
        & $Parts[0] @rest
    }
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE)" }
}

# ── collect params ─────────────────────────────────────────────────────────────
if (-not $ProjectId)    { $ProjectId    = Ask "GCP Project ID" (gcloud config get-value project 2>$null) }
if (-not $Bucket)       { $Bucket       = Ask "Firebase Storage bucket (e.g. my-project.appspot.com)" }
if (-not $PodcastEmail) { $PodcastEmail = Ask "Podcast owner email (used in RSS feed, not stored in repo)" }

$ImageTag  = "gcr.io/$ProjectId/$ServiceName"

Write-Host "`n== GospelPodcast deploy ==========================================" -ForegroundColor Yellow
Write-Host "  Project : $ProjectId"
Write-Host "  Bucket  : $Bucket"
Write-Host "  Image   : $ImageTag"
Write-Host "  Region  : $Region"
Write-Host "  Service : $ServiceName"
Write-Host "=================================================================" -ForegroundColor Yellow

# ── 1. set project ─────────────────────────────────────────────────────────────
RunOrDie "gcloud","config","set","project",$ProjectId

# ── 2. enable required APIs ───────────────────────────────────────────────────
Write-Host "`n[1/6] Enabling required APIs..." -ForegroundColor Green
RunOrDie "gcloud","services","enable","run.googleapis.com","cloudbuild.googleapis.com","cloudscheduler.googleapis.com","artifactregistry.googleapis.com","firebasestorage.googleapis.com","--project",$ProjectId

# ── 3. deploy Firebase Storage security rules ──────────────────────────────────
Write-Host "`n[2/6] Deploying Firebase Storage rules..." -ForegroundColor Green
if (Get-Command firebase -ErrorAction SilentlyContinue) {
    RunOrDie "firebase","use",$ProjectId
    RunOrDie "firebase","deploy","--only","storage","--project",$ProjectId
} else {
    Write-Host "  [SKIP] Firebase CLI not found. Install with: npm install -g firebase-tools" -ForegroundColor Yellow
    Write-Host "  Then run: firebase deploy --only storage --project $ProjectId" -ForegroundColor Yellow
    Write-Host "  Storage rules file: storage.rules" -ForegroundColor Yellow
}

# ── 4. build image via Cloud Build ────────────────────────────────────────────
Write-Host "`n[3/6] Building Docker image..." -ForegroundColor Green
RunOrDie "gcloud","builds","submit",".","--config","cloudbuild.yaml","--project",$ProjectId

# Re-tag if the build used $PROJECT_ID substitution already; nothing extra needed.

# ── 5. deploy Cloud Run service ───────────────────────────────────────────────
Write-Host "`n[4/6] Deploying Cloud Run service..." -ForegroundColor Green

# Dedicated service account for Cloud Run (storage access)
$RunSA = "gospel-run-sa@$ProjectId.iam.gserviceaccount.com"
$saExists = gcloud iam service-accounts list --filter="email=$RunSA" --format="value(email)" 2>$null
if (-not $saExists) {
    RunOrDie "gcloud","iam","service-accounts","create","gospel-run-sa","--display-name=GospelPodcast Cloud Run SA","--project",$ProjectId
}
RunOrDie "gcloud","projects","add-iam-policy-binding",$ProjectId,"--member=serviceAccount:$RunSA","--role=roles/storage.objectAdmin","--condition=None"

RunOrDie "gcloud","run","deploy",$ServiceName,
    "--image",$ImageTag,
    "--region",$Region,
    "--platform","managed",
    "--no-allow-unauthenticated",
    "--service-account",$RunSA,
    "--set-env-vars","FIREBASE_BUCKET=$Bucket,TZ=$TimeZone,PODCAST_EMAIL=$PodcastEmail",
    "--memory","512Mi",
    "--timeout","300",
    "--project",$ProjectId

# Allow public access via IAM (allUsers invoker)
RunOrDie "gcloud","run","services","add-iam-policy-binding",$ServiceName,
    "--member=allUsers",
    "--role=roles/run.invoker",
    "--region",$Region,
    "--project",$ProjectId

# Retrieve the deployed service URL
$RunUrl = (gcloud run services describe $ServiceName --region $Region --format "value(status.url)" --project $ProjectId)
Write-Host "  Cloud Run URL: $RunUrl" -ForegroundColor Cyan

# ── 6. service account for Scheduler (invoke Cloud Run) ───────────────────────
Write-Host "`n[5/6] Configuring Cloud Scheduler service account..." -ForegroundColor Green
$SchedSA = "gospel-scheduler-sa@$ProjectId.iam.gserviceaccount.com"
$schedSaExists = gcloud iam service-accounts list --filter="email=$SchedSA" --format="value(email)" 2>$null
if (-not $schedSaExists) {
    RunOrDie "gcloud","iam","service-accounts","create","gospel-scheduler-sa","--display-name=GospelPodcast Scheduler SA","--project",$ProjectId
}
RunOrDie "gcloud","run","services","add-iam-policy-binding",$ServiceName,"--region",$Region,"--member=serviceAccount:$SchedSA","--role=roles/run.invoker","--project",$ProjectId

# ── 7. create Cloud Scheduler jobs (one per language, staggered 2 min apart) ──
Write-Host "`n[6/6] Creating Cloud Scheduler jobs..." -ForegroundColor Green

$langs = @(
    @{ code = "it"; minute = 0  },
    @{ code = "en"; minute = 2  },
    @{ code = "de"; minute = 4  },
    @{ code = "fr"; minute = 6  },
    @{ code = "es"; minute = 8  },
    @{ code = "pt"; minute = 10 }
)

foreach ($lang in $langs) {
    $code     = $lang.code
    $min      = $lang.minute
    $hour     = 6
    $schedule = "$min $hour * * *"
    $jobName  = "gospel-publish-$code"
    $uri      = "$RunUrl/publish?lang=$code"

    # Delete existing job silently so re-run is idempotent (ignore NOT_FOUND on first run)
    try { gcloud scheduler jobs delete $jobName --location $Region --quiet --project $ProjectId *>$null } catch { }
    $LASTEXITCODE = 0

    RunOrDie "gcloud","scheduler","jobs","create","http",$jobName,
        "--location",$Region,
        "--schedule=$schedule",
        "--time-zone=$TimeZone",
        "--uri=$uri",
        "--http-method=POST",
        "--oidc-service-account-email=$SchedSA",
        "--project",$ProjectId
    $minPadded = '{0:D2}' -f $min
    Write-Host "  Scheduled $code at ${hour}:$minPadded $TimeZone -> $uri" -ForegroundColor Gray
}

# ── summary ───────────────────────────────────────────────────────────────────
Write-Host "`n=================================================================" -ForegroundColor Yellow
Write-Host "  Deploy complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Cloud Run : $RunUrl"
  Write-Host "  Health    : $RunUrl/ping"
Write-Host ""
Write-Host "  RSS feeds (register these once in Spotify for Creators):"
foreach ($lang in $langs) {
    $code = $lang.code
    Write-Host "    $code : https://storage.googleapis.com/$Bucket/gospel/$code/podcast_feed.xml"
}
Write-Host ""
Write-Host "  Jobs run daily at 06:00-06:10 $TimeZone, 2-min stagger per language."
Write-Host "=================================================================" -ForegroundColor Yellow
