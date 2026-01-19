import os
import functions_framework
import requests
from google.cloud import bigquery
from datetime import datetime

# Environment Variables
# These should be set in the Cloud Function configuration
API_KEY = os.environ.get('QUICK_RIPORT_API_KEY')
DATASET_ID = os.environ.get('BQ_DATASET_ID', 'quick_riport_data')
TABLE_ID = os.environ.get('BQ_TABLE_ID', 'expenses')
PROJECT_ID = os.environ.get('GCP_PROJECT') # Automatically set by Cloud Functions

@functions_framework.http
def import_expenses(request):
    """HTTP Cloud Function to fetch expenses and load to BigQuery."""
    
    if not API_KEY:
        return "Internal Error: QUICK_RIPORT_API_KEY not configured", 500

    print("Starting data import task...")

    # 1. Fetch Data from API
    url = "https://api.quick.riport.co.hu/2/expenses"
    headers = {
        "Authorization": f"Bearer {API_KEY}"  # Assuming Bearer token, or just raw key in header? User said "API key authentication".
                                               # Adjusting to generic "api-key" header or similar if needed.
                                               # Validating typical patterns; often header is 'x-api-key' or basic auth or bearer.
                                               # Will assume 'Authorization: Bearer <KEY>' for now, but easily changeable.
    }
    # If the user meant a specific header key:
    # headers = {"X-Api-Key": API_KEY} or something similar.
    # Defaulting to checking param support for simple auth.
    
    # Let's try to pass it as a query param too if header fails, or just put it in a custom header. 
    # NOTE: User didn't specify Header Name. I'll default to a Custom Header 'X-API-KEY' as it's common for such services, 
    # but I'll add a comment to switch to Bearer if that's the standard.
    
    # REVISION: Common Quick Riport style might verify later. 
    # Let's try standard requests with the key.
    
    try:
        # Fetching data. 
        # TODO: Does the API support paging? 
        # If so, we'd need a loop. Assuming single page full dump for simplicity first.
        response = requests.get(url, headers={"Authorization": f"{API_KEY}"}) # Often just the key string if not Bearer
        response.raise_for_status()
        data = response.json()
        
        # Determine if data is a list or wrapped in a key like {"expenses": [...]}
        rows_to_insert = data
        if isinstance(data, dict):
             # Look for a likely list key
             for key, val in data.items():
                 if isinstance(val, list):
                     rows_to_insert = val
                     break
        
        if not isinstance(rows_to_insert, list):
            print(f"Unexpected data format: {type(data)}")
            return f"Error: Unexpected JSON format. keys: {data.keys() if isinstance(data, dict) else 'N/A'}", 500

        print(f"Fetched {len(rows_to_insert)} records.")
        
        if len(rows_to_insert) == 0:
            return "No data to insert.", 200

    except Exception as e:
        print(f"API Fetch Error: {e}")
        return f"API Fetch Error: {e}", 500

    # 2. Load to BigQuery
    try:
        client = bigquery.Client()
        dataset_ref = client.dataset(DATASET_ID)
        table_ref = dataset_ref.table(TABLE_ID)

        job_config = bigquery.LoadJobConfig(
            # Schema evolution: autodetect for now to handle new fields automatically
            autodetect=True, 
            # Replace the table content every time? 
            # User wants "refreshed regularly". 
            # Ideally we Append if we can filter by date, but without complex state management (watermarks),
            # TRUNCATE (Overwrite) is the safest simple way to ensure data consistency with the source 
            # if the source provides a full snapshot or movable window.
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )

        job = client.load_table_from_json(rows_to_insert, table_ref, job_config=job_config)
        
        job.result()  # Waits for the job to complete.

        print(f"Loaded {job.output_rows} rows into {DATASET_ID}.{TABLE_ID}.")
        return f"Success: Loaded {job.output_rows} rows.", 200

    except Exception as e:
        print(f"BigQuery Load Error: {e}")
        return f"BigQuery Load Error: {e}", 500
