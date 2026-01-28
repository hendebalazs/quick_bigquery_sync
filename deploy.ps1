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
    # Check if dataset exists
    Write-Host "   Checking for dataset $DATASET_ID..." -ForegroundColor Gray
    $bq_show_res = & $BQ_CMD --project_id=$PROJECT_ID show "$DATASET_ID" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
         Write-Host "   Dataset already exists." -ForegroundColor Green
    } else {
         # Attempt create if verification failed with "Not found"
         if ($bq_show_res -match "Not found") {
             Write-Host "   Dataset not found. Attempting to create..." -ForegroundColor Yellow
             & $BQ_CMD --project_id=$PROJECT_ID --location=$REGION mk -d --description "Data form Quick Riport" "$DATASET_ID" 2>&1 | Out-Null
             if ($LASTEXITCODE -eq 0) {
                Write-Host "   Dataset created successfully." -ForegroundColor Green
             } else {
                Write-Host "   Dataset creation attempt failed. The Cloud Function might attempt auto-creation if it has permissions." -ForegroundColor Red
             }
         } else {
             Write-Host "   Warning: Dataset verification check returned an error. Please check your permissions or if the Project ID is correct." -ForegroundColor Red
             Write-Host "   Error: $bq_show_res" -ForegroundColor Gray
             Write-Host "   Continuing with deployment anyway..." -ForegroundColor Gray
         }
    }
}


# 1.5 Handle API Key Security
Write-Host "`n1.5 Checking for API Key..." -ForegroundColor Yellow
$API_KEY_TO_DEPLOY = $null

# Priority 1: Check if already set in current shell environment
if ($env:QUICK_RIPORT_API_KEY) {
    $API_KEY_TO_DEPLOY = $env:QUICK_RIPORT_API_KEY
    Write-Host "   Found API Key in environment variables." -ForegroundColor Green
}
# Priority 2: Check for a local git-ignored settings file
elseif (Test-Path "local_settings.ps1") {
    . ./local_settings.ps1
    if ($QUICK_RIPORT_API_KEY) {
        $API_KEY_TO_DEPLOY = $QUICK_RIPORT_API_KEY
        Write-Host "   Found API Key in local_settings.ps1." -ForegroundColor Green
    }
}

if (-not $API_KEY_TO_DEPLOY) {
    Write-Host "   WARNING: QUICK_RIPORT_API_KEY not found." -ForegroundColor Red
    Write-Host "   The Cloud Function will be deployed with its EXISTING key (if any)."
    Write-Host "   To set it securely, run: `$env:QUICK_RIPORT_API_KEY='your_key_here'` before running this script."
}

# 2. Deploy Cloud Function
Write-Host "`n2. Deploying Cloud Function ($FUNCTION_NAME)..." -ForegroundColor Yellow
# Build environment variables list
$ENV_VARS = "BQ_DATASET_ID=$DATASET_ID,GCP_PROJECT=$PROJECT_ID,PYTHONUNBUFFERED=True"
if ($API_KEY_TO_DEPLOY) {
    $ENV_VARS += ",QUICK_RIPORT_API_KEY=$API_KEY_TO_DEPLOY"
}

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
    --set-env-vars $ENV_VARS

Write-Host "   Cloud Function Deployment initiated..." -ForegroundColor Green

# 2.5 Grant Invoker Permission
Write-Host "`n2.5 Granting Invoker Permission to Service Account..." -ForegroundColor Yellow

# Dynamically fetch the service account email used by the function
$FUNCTION_INFO = gcloud functions describe $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --format="json" | ConvertFrom-Json
$SERVICE_ACCOUNT = $FUNCTION_INFO.serviceConfig.serviceAccountEmail

if (-not $SERVICE_ACCOUNT) {
    Write-Host "   WARNING: Could not fetch service account email from function. Falling back to default appspot account." -ForegroundColor Gray
    $SERVICE_ACCOUNT = "$PROJECT_ID@appspot.gserviceaccount.com"
}

Write-Host "   Detected Service Account: $SERVICE_ACCOUNT" -ForegroundColor Cyan

# For Gen 2 functions (Cloud Run), we need to grant roles/run.invoker
# Correct command is 'gcloud run services add-iam-policy-binding'
gcloud run services add-iam-policy-binding $FUNCTION_NAME `
    --project=$PROJECT_ID `
    --region=$REGION `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/run.invoker"

Write-Host "   Permission granted to $SERVICE_ACCOUNT." -ForegroundColor Green

# 2.6 Grant BigQuery Permissions
Write-Host "`n2.6 Granting BigQuery Admin Permission to Service Account..." -ForegroundColor Yellow
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/bigquery.admin"

Write-Host "   BigQuery permissions granted to $SERVICE_ACCOUNT." -ForegroundColor Green

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
