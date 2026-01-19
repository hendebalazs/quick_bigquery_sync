import os
import sys
import json
import requests
from main import import_expenses

# Mock the environment
os.environ['GCP_PROJECT'] = 'test-project'
os.environ['QUICK_RIPORT_API_KEY'] = 'YOUR_API_KEY_HERE' # User must replace this or set env var
os.environ['BQ_DATASET_ID'] = 'quick_riport_data_test'
os.environ['BQ_TABLE_ID'] = 'expenses_test'

def test_api_fetch():
    """Manual test to just check the API response structure"""
    print("Testing API fetch only...")
    api_key = os.environ.get('QUICK_RIPORT_API_KEY')
    if api_key == 'YOUR_API_KEY_HERE':
        print("ERROR: Please set 'QUICK_RIPORT_API_KEY' environment variable or edit this script with your key.")
        return

    url = "https://api.quick.riport.co.hu/2/expenses"
    headers = {"Authorization": f"{api_key}"}
    
    try:
        resp = requests.get(url, headers=headers)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print("Response Data Sample (First Item):")
            
            # Helper logic to extract list
            rows = data
            if isinstance(data, dict):
                 for key, val in data.items():
                     if isinstance(val, list):
                         rows = val
                         print(f"Found list under key: '{key}'")
                         break
            
            if rows and len(rows) > 0:
                print(json.dumps(rows[0], indent=2))
            else:
                print("Response is empty list or could not find list.")
        else:
            print("Response Headers:", resp.headers)
            print("Response Text:", resp.text)
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "integration":
        # Simulate Cloud Function Request
        # NOTE: This requires Authenticated Google Creds locally (gcloud auth application-default login)
        print("Running full integration test (API -> BigQuery)...")
        class MockRequest:
            def __init__(self):
                self.args = {}
                self.data = {}
        
        res = import_expenses(MockRequest())
        print("Result:", res)
    else:
        test_api_fetch()
