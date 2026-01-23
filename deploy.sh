#!/bin/bash

# Configuration
PROJECT_ID="quick-riport"
REGION="europe-west1" # Choose a region close to you
FUNCTION_NAME="quick-riport-loader"
DATASET_ID="quick_riport_data"
TOPIC_NAME="trigger-quick-riport-sync"
SCHEDULER_JOB_NAME="quick_riport_cron"

# 1. Create BigQuery Dataset if not exists
echo "Creating BigQuery Dataset..."
bq --project=$PROJECT_ID --location=$REGION mk -d --description "Data form Quick Riport" $DATASET_ID

# 2. Deploy Cloud Function
echo "Deploying Cloud Function..."
gcloud functions deploy $FUNCTION_NAME \
    --project=$PROJECT_ID \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=. \
    --entry-point=import_expenses \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars BQ_DATASET_ID=$DATASET_ID \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    # Note: sensitive key should be in Secret Manager ideally, but Env Var is okay for MVP
    # --set-env-vars QUICK_RIPORT_API_KEY="YOUR_KEY" (Set this in console or via a separate command to avoid committing it)

# 3. Create Cloud Scheduler Job
echo "Creating Cloud Scheduler Job..."
# This example uses an HTTP trigger to the function URL. 
# You need to get the function URL first.
# Fetch the function URL first
FUNCTION_URI=$(gcloud functions describe $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --format='value(serviceConfig.uri)')

gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
    --project=$PROJECT_ID \
    --schedule="0 */4 * * *" \
    --uri=$FUNCTION_URI \
    --http-method=GET \
    --location=$REGION \
    --time-zone="Europe/Budapest"
    
echo "Deployment Complete. URL: $FUNCTION_URI"
