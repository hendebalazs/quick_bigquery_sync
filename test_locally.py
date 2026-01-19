import os
import sys
import json
import requests
from main import import_expenses

# Mock the environment
os.environ['GCP_PROJECT'] = 'test-project'
if 'QUICK_RIPORT_API_KEY' not in os.environ:
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
    headers = {"Authorization": f"Token {api_key}"} # Updated to match docs 'Token <KEY>'
    
    try:
        resp = requests.get(url, headers=headers)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print("Full Response Keys:", data.keys() if isinstance(data, dict) else "Not a dict")
            if isinstance(data, dict) and 'results' in data:
                print(f"Type of 'results': {type(data['results'])}")
                if isinstance(data['results'], dict):
                     print(f"Results Keys (first 10): {list(data['results'].keys())[:10]}")
                elif isinstance(data['results'], list):
                     print(f"Results is a list of len {len(data['results'])}")

            # Extract Reference Data (if present on this page)
            results_node = None
            if isinstance(data, dict):
                 if 'results' in data and isinstance(data['results'], dict):
                     results_node = data['results']
                 elif 'expenses' in data: 
                     results_node = data

            if results_node:
                print("Found Results Node keys:", results_node.keys())
                for key in ['currencies', 'tags', 'expense_types', 'accounts', 'expenses']:
                    if key in results_node:
                        val = results_node[key]
                        count = len(val) if isinstance(val, list) else 'Not a list'
                        print(f"Entity '{key}': Found {count} items.")
                        if isinstance(val, list) and len(val) > 0:
                            print(f"  Sample {key}[0]: {json.dumps(val[0])[:200]}...")

            # Extract Expenses & Assignments check
            expenses = []
            if results_node and 'expenses' in results_node:
                expenses = results_node['expenses']
            
            if expenses:
                print(f"Found {len(expenses)} expenses.")
                # Check for assignments
                assignments_found = 0
                for exp in expenses:
                    if 'assignments' in exp and exp['assignments']:
                        assignments_found += len(exp['assignments'])
                print(f"Found {assignments_found} assignments nested within expenses.")
            else:
                print("No expenses found.")
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
