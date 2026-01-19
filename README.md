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

## Architecture

*   **Cloud Function (`main.py`)**: Fetches data and loads to BQ.
*   **BigQuery**: Stores the data. Tables are auto-created/updated.
*   **Cloud Scheduler**: Triggers the function every 4 hours.

## Note on BigQuery Data Refresh

The function uses `WRITE_TRUNCATE` disposition, meaning it **replaces** the table content on each run. This ensures the data in BigQuery exactly matches the current state of the API (assuming the API returns a full snapshot).
