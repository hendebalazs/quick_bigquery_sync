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

    # 1. Fetch References & Data from API
    base_url = "https://api.quick.riport.co.hu/2/expenses"
    headers = {
        "Authorization": f"Token {API_KEY}",
        "Content-Type": "application/json"
    }

    # Data containers
    all_expenses = []
    all_assignments = []
    
    # Reference data (using dicts to deduplicate by ID across pages)
    ref_currencies = {}
    ref_tags = {}
    ref_expense_types = {}
    ref_accounts = {}

    page = 1
    page_size = 200
    
    try:
        while True:
            print(f"Fetching page {page}...")
            params = {
                "page": page,
                "page_size": page_size
            }
            
            response = requests.get(base_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Extract Reference Data (if present on this page)
            results_node = None
            if isinstance(data, dict):
                 if 'results' in data and isinstance(data['results'], dict):
                     results_node = data['results']
                 # Fallback for flat structure
                 elif 'expenses' in data: 
                     # If format is flat {expenses: [], currencies: []}
                     results_node = data
            
            if results_node:
                # Helper to update ref dicts
                def update_refs(node, key, target_dict):
                    if key in node and isinstance(node[key], list):
                        for item in node[key]:
                            if isinstance(item, dict) and 'id' in item:
                                target_dict[item['id']] = item

                update_refs(results_node, 'currencies', ref_currencies)
                update_refs(results_node, 'tags', ref_tags)
                update_refs(results_node, 'expense_types', ref_expense_types)
                update_refs(results_node, 'accounts', ref_accounts)

            # Extract Expenses
            rows_on_page = []
            if results_node and 'expenses' in results_node and isinstance(results_node['expenses'], list):
                rows_on_page = results_node['expenses']
            elif isinstance(data, dict) and 'results' in data and isinstance(data['results'], list):
                 # Old fallback
                 rows_on_page = data['results']
            
            # Process this page's expenses
            for expense in rows_on_page:
                if not isinstance(expense, dict): continue
                
                # Extract Assignments
                if 'assignments' in expense and isinstance(expense['assignments'], list):
                    for assignment in expense['assignments']:
                        if isinstance(assignment, dict):
                            # Link back to expense
                            assignment['expense_id'] = expense.get('id')
                            all_assignments.append(assignment)
                    
                    # Remove assignments from expense dict to normalize
                    del expense['assignments']
                
                all_expenses.append(expense)

            count = len(rows_on_page)
            print(f"Page {page}: Fetched {count} expenses.")
            
            if count < page_size:
                break
            
            page += 1
            if page > 1000:
                print("Warning: Reached 1000 pages limit.")
                break

        print(f"Total Fetched: Expenses={len(all_expenses)}, Assignments={len(all_assignments)}")

        if len(all_expenses) == 0:
            return "No data to insert.", 200

    except Exception as e:
        print(f"API Fetch Error: {e}")
        return f"API Fetch Error: {e}", 500

    # 2. Load to BigQuery (Multiple Tables)
    try:
        client = bigquery.Client()
        dataset_ref = client.dataset(DATASET_ID)
        
        # Helper to load a list of dicts to a table
        def load_table(table_name, rows, check_empty=True):
            if check_empty and not rows:
                print(f"Skipping {table_name} (no data).")
                return
            
            print(f"Loading {len(rows)} rows into {table_name}...")
            table_ref = dataset_ref.table(table_name)
            job_config = bigquery.LoadJobConfig(
                autodetect=True, 
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            )
            job = client.load_table_from_json(rows, table_ref, job_config=job_config)
            job.result()
            print(f"Success: Loaded {table_name}.")

        # Load all tables
        # User defined TABLE_ID for expenses, but we have multiple now. 
        # We will use TABLE_ID for the main expenses table, and suffixes/names for others?
        # Or just fixed names? User said "corresponding tables".
        # Let's use fixed names typically, or derive from TABLE_ID.
        # Default TABLE_ID is 'expenses'.
        
        load_table(TABLE_ID, all_expenses)
        load_table(f"{TABLE_ID}_assignments", all_assignments) # e.g. expenses_assignments
        load_table('currencies', list(ref_currencies.values()))
        load_table('tags', list(ref_tags.values()))
        load_table('expense_types', list(ref_expense_types.values()))
        load_table('accounts', list(ref_accounts.values()))

        return f"Success: Loaded {len(all_expenses)} expenses and related tables.", 200

    except Exception as e:
        print(f"BigQuery Load Error: {e}")
        return f"BigQuery Load Error: {e}", 500
