# Quick Riport to BigQuery Pipeline

This project contains a Google Cloud Function to fetch expenses from Quick Riport and load them into BigQuery.

## Prerequisites

1.  **Google Cloud Platform Project**: You need a GCP project with billing enabled.
2.  **APIs Enabled**:
    *   Cloud Functions API
    *   Cloud Build API
    *   BigQuery API
    *   Cloud Scheduler API
3.  **gcloud CLI**: Installed and authenticated (`gcloud auth login`).

## Setup

1.  **Clone/Open this repository**.
2.  **Set your API Key**:
    You need to set your Quick Riport API Key in the environment variables for deployment.

## Local Testing

You can test the API connection and data format locally without deploying.

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Run the test script:
    ```bash
    # Replace YOUR_KEY with your actual API key
    set QUICK_RIPORT_API_KEY=YOUR_KEY
    python test_locally.py
    ```
    This will print the first record found to the console.

## Deployment

1.  Open `deploy.sh` and update the `PROJECT_ID` and `REGION` variables.
2.  Run the deployment script:
    ```bash
    # You might need to make it executable first if using bash/WSL: chmod +x deploy.sh
    ./deploy.sh
    ```
    *Note: You can also copy the `gcloud` commands from `deploy.sh` and run them in PowerShell.*

## Free Tier Usage & Client Handoff

**IMPORTANT**: To ensure the usage counts against your **Client's Free Tier** (not yours), you must deploy this solution into a Google Cloud Project **owned by the client**.

### 1. Client Setup
Ask your client to:
1.  Create a new Google Cloud Project (e.g., `remote-reporting-project`).
2.  Enable Billing on that project (required for Cloud Build/Functions, even for free tier).
3.  Add your email address as an **Editor** or **Owner** in the project's IAM settings.

### 2. Your Deployment Steps
Once you have access:
1.  Login to their project:
    ```bash
    gcloud auth login
    gcloud config set project [CLIENT_PROJECT_ID]
    ```
2.  Open `deploy.sh` and ensure `PROJECT_ID` matches the client's project ID.
3.  Run `./deploy.sh`.

### 3. Estimated Costs (Free Tier Limits)
This solution is designed to fit comfortably within the Google Cloud Free Tier provided the client hasn't used it up elsewhere:
*   **Cloud Functions**: ~180 invocations/month (Limit: 2 Million/month). **FREE**.
*   **Cloud Scheduler**: 1 Job (Limit: 3 Jobs/month). **FREE**.
*   **BigQuery**: 
    *   Storage: < 1GB active (Limit: 10GB/month). **FREE**.
    *   Processing: Negligible for this volume (Limit: 1TB/month). **FREE**.

*Note: Free tier limits are subject to change by Google. Always check official pricing.*

## Architecture

*   **Cloud Function (`main.py`)**: Fetches data (pagination via `next` URL) and loads to BQ.
*   **BigQuery**: Stores the data. Tables are auto-created and **overwritten** (Snapshot strategy) on each run.
*   **Cloud Scheduler**: Triggers the function every 4 hours.

## Manual Testing & Verification

To verify the pipeline immediately, run this command in PowerShell:

```powershell
gcloud scheduler jobs run quick_riport_cron --project=quick-riport --location=europe-west1
```

Replace `quick-riport` with your actual Project ID if different. This command triggers the scheduler job, which in turn authenticates and calls the Cloud Function.

