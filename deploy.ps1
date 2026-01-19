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
try {
    # Check if dataset exists prevents error
    bq show "$PROJECT_ID`:$DATASET_ID" | Out-Null
    Write-Host "   Dataset already exists." -ForegroundColor Green
} catch {
    # Attempt create
    try {
        bq --location=$REGION mk -d --description "Data form Quick Riport" "$PROJECT_ID`:$DATASET_ID"
        Write-Host "   Dataset created successfully." -ForegroundColor Green
    } catch {
        Write-Host "   Error creating dataset (might already exist or permission issue): $_" -ForegroundColor Red
        # Continue mostly safe if it exists
    }
}

# 2. Deploy Cloud Function
Write-Host "`n2. Deploying Cloud Function ($FUNCTION_NAME)..." -ForegroundColor Yellow
# Note: Using ` (backtick) for line continuation in PowerShell
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --runtime=python310 `
    --region=$REGION `
    --source=. `
    --entry-point=import_expenses `
    --trigger-http `
    --allow-unauthenticated `
    --set-env-vars BQ_DATASET_ID=$DATASET_ID `
    --set-env-vars GCP_PROJECT=$PROJECT_ID 
    # --set-env-vars QUICK_RIPORT_API_KEY="YOUR_KEY" # Uncomment if not setting via Console

Write-Host "   Cloud Function Deployment initiated..." -ForegroundColor Green

# 3. Create Cloud Scheduler Job
Write-Host "`n3. Creating Cloud Scheduler Job ($SCHEDULER_JOB_NAME)..." -ForegroundColor Yellow

# Fetch the function URL first
$FUNCTION_URI = gcloud functions describe $FUNCTION_NAME --region=$REGION --format='value(serviceConfig.uri)'
Write-Host "   Target Function URL: $FUNCTION_URI" -ForegroundColor Cyan

if ($FUNCTION_URI) {
    # Check if job exists to decide create or update
    $JobExists = gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$REGION 2>$null
    
    if ($JobExists) {
         Write-Host "   Updating existing job..."
         gcloud scheduler jobs update http $SCHEDULER_JOB_NAME `
            --schedule="0 */4 * * *" `
            --uri=$FUNCTION_URI `
            --http-method=GET `
            --location=$REGION `
            --time-zone="Europe/Budapest"
    } else {
         Write-Host "   Creating new job..."
         gcloud scheduler jobs create http $SCHEDULER_JOB_NAME `
            --schedule="0 */4 * * *" `
            --uri=$FUNCTION_URI `
            --http-method=GET `
            --location=$REGION `
            --time-zone="Europe/Budapest"
    }
    Write-Host "   Scheduler Job configured." -ForegroundColor Green
} else {
    Write-Host "   CRITICAL ERROR: Could not retrieve Cloud Function URL. Deployment failed." -ForegroundColor Red
    exit 1
}

Write-Host "`nDeployment Complete!" -ForegroundColor Green
