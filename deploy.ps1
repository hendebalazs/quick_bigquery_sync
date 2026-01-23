# Configuration
$PROJECT_ID = "quick-riport"  # Set your Project ID here
$REGION = "europe-west1"
$FUNCTION_NAME = "quick-riport-loader"
$DATASET_ID = "quick_riport_data"
$SCHEDULER_JOB_NAME = "quick_riport_cron"

# Error handling
$ErrorActionPreference = "Stop"

Write-Host "Starting Deployment to Project: $PROJECT_ID in $REGION" -ForegroundColor Cyan

# 1. Create BigQuery Dataset if not exists
Write-Host "1. Creating BigQuery Dataset ($DATASET_ID)..." -ForegroundColor Yellow

# Function to find BQ executable
function Get-BqCommand {
    if (Get-Command bq -ErrorAction SilentlyContinue) {
        return "bq"
    }
    # Try to find relative to gcloud
    $gcloudPath = (Get-Command gcloud -ErrorAction SilentlyContinue).Source
    if ($gcloudPath) {
        $binDir = Split-Path -Parent $gcloudPath
        $bqPath = Join-Path $binDir "bq.cmd"
        if (Test-Path $bqPath) { return $bqPath }
        $bqPathExe = Join-Path $binDir "bq.exe"
        if (Test-Path $bqPathExe) { return $bqPathExe }
    }
    return $null
}

$BQ_CMD = Get-BqCommand

if (-not $BQ_CMD) {
    Write-Host "   WARNING: 'bq' command not found. Skipping dataset creation logic." -ForegroundColor Red
    Write-Host "   Please ensure Google Cloud SDK is installed and 'bq' is in your PATH."
    Write-Host "   (Restarting your terminal usually fixes this after install)."
} else {
    try {
        # Check if dataset exists
        & $BQ_CMD --project=$PROJECT_ID show "$DATASET_ID" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
             Write-Host "   Dataset already exists." -ForegroundColor Green
        } else {
             # Attempt create
             Write-Host "   Dataset not found. Attempting to create..." -ForegroundColor Gray
             & $BQ_CMD --project=$PROJECT_ID --location=$REGION mk -d --description "Data form Quick Riport" "$DATASET_ID" 2>&1 | Out-Null
             if ($LASTEXITCODE -eq 0) {
                Write-Host "   Dataset created successfully." -ForegroundColor Green
             } else {
                Write-Host "   Dataset creation skipped (might already exist or check failed). The Cloud Function will attempt auto-creation if needed." -ForegroundColor Gray
             }
        }
    } catch {
        Write-Host "   Note: Dataset verification skipped (non-fatal). Deployment will continue." -ForegroundColor Gray
    }
}

# 2. Deploy Cloud Function
Write-Host "`n2. Deploying Cloud Function ($FUNCTION_NAME)..." -ForegroundColor Yellow
# Note: Using ` (backtick) for line continuation in PowerShell
gcloud functions deploy $FUNCTION_NAME `
    --project=$PROJECT_ID `
    --gen2 `
    --runtime=python311 `
    --region=$REGION `
    --source=. `
    --entry-point=import_expenses `
    --trigger-http `
    --no-allow-unauthenticated `
    --memory=512Mi `
    --timeout=540s `
    --set-env-vars BQ_DATASET_ID=$DATASET_ID `
    --set-env-vars GCP_PROJECT=$PROJECT_ID `
    --set-env-vars PYTHONUNBUFFERED=True 
    # --set-env-vars QUICK_RIPORT_API_KEY="YOUR_KEY" # Uncomment if not setting via Console

Write-Host "   Cloud Function Deployment initiated..." -ForegroundColor Green

# 2.5 Grant Invoker Permission
Write-Host "`n2.5 Granting Invoker Permission to Service Account..." -ForegroundColor Yellow
$SERVICE_ACCOUNT = "$PROJECT_ID@appspot.gserviceaccount.com"
# For Gen 2 functions (Cloud Run), we need to grant roles/run.invoker
# Correct command is 'gcloud run services add-iam-policy-binding'
gcloud run services add-iam-policy-binding $FUNCTION_NAME `
    --project=$PROJECT_ID `
    --region=$REGION `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/run.invoker"

Write-Host "   Permission granted to $SERVICE_ACCOUNT." -ForegroundColor Green

# 3. Create Cloud Scheduler Job
Write-Host "`n3. Creating Cloud Scheduler Job ($SCHEDULER_JOB_NAME)..." -ForegroundColor Yellow

# Fetch the function URL first
$FUNCTION_URI = gcloud functions describe $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --format='value(serviceConfig.uri)'
Write-Host "   Target Function URL: $FUNCTION_URI" -ForegroundColor Cyan

if ($FUNCTION_URI) {
    # Check if job exists to decide create or update
    $JobExists = $false
    try {
        gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --project=$PROJECT_ID --location=$REGION 2>$null | Out-Null
        $JobExists = $true
    } catch {
        # Job does not exist, safe to ignore error
        $JobExists = $false
    }
    
    if ($JobExists) {
         Write-Host "   Updating existing job..."
         gcloud scheduler jobs update http $SCHEDULER_JOB_NAME `
            --project=$PROJECT_ID `
            --schedule="0 */4 * * *" `
            --uri=$FUNCTION_URI `
            --http-method=GET `
            --location=$REGION `
            --time-zone="Europe/Budapest" `
            --oidc-service-account-email="$PROJECT_ID@appspot.gserviceaccount.com"
    } else {
         Write-Host "   Creating new job..."
         gcloud scheduler jobs create http $SCHEDULER_JOB_NAME `
            --project=$PROJECT_ID `
            --schedule="0 */4 * * *" `
            --uri=$FUNCTION_URI `
            --http-method=GET `
            --location=$REGION `
            --time-zone="Europe/Budapest" `
            --oidc-service-account-email="$PROJECT_ID@appspot.gserviceaccount.com"
    }
    Write-Host "   Scheduler Job configured." -ForegroundColor Green
} else {
    Write-Host "   CRITICAL ERROR: Could not retrieve Cloud Function URL. Deployment failed." -ForegroundColor Red
    exit 1
}

Write-Host "`nDeployment Complete!" -ForegroundColor Green
Write-Host "To test the pipeline manually, run:" -ForegroundColor Cyan
Write-Host "gcloud scheduler jobs run $SCHEDULER_JOB_NAME --project=$PROJECT_ID --location=$REGION" -ForegroundColor White
