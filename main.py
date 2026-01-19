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

    # 2. Data Enrichment (Flattening & ID Resolution)
    print("Enriching data (resolving IDs to names)...")
    
    def resolve_id(obj, field, ref_dict, target_field=None):
        """Replaces ID in 'field' with name from 'ref_dict'. 
           If target_field is set, writes to that instead of overwriting."""
        if field in obj and obj[field] is not None:
            ref_id = obj[field]
            if ref_id in ref_dict:
                obj[target_field or field] = ref_dict[ref_id].get('name')
            else:
                # Keep ID if name not found, or maybe convert to string?
                # User asked to replace. If not found, keeping ID is safer info preservation.
                pass
    
    def resolve_list(obj, field, ref_dict):
        """Converts list of IDs to comma-separated string of names."""
        if field in obj and isinstance(obj[field], list):
            names = []
            for item in obj[field]:
                # Item could be ID (int) or dict?
                # Based on sample simple_tags is list of ints.
                # tags might be list of dicts or ints.
                ref_id = item
                if isinstance(item, dict) and 'id' in item:
                    ref_id = item['id']
                
                if ref_id in ref_dict:
                    names.append(ref_dict[ref_id].get('name'))
                else:
                    names.append(str(ref_id))
            
            # Flatten to string
            obj[field] = ", ".join(names)

    # Process Expenses
    for exp in all_expenses:
        resolve_id(exp, 'currency', ref_currencies)
        resolve_id(exp, 'account', ref_accounts)
        
        # Merge tags and simple_tags if needed, or just resolve both
        # Sample shows simple_tags has the IDs.
        resolve_list(exp, 'tags', ref_tags)
        resolve_list(exp, 'simple_tags', ref_tags) 
        # If simple_tags is the main one, maybe copy to tags? 
        # Let's keep both resolved.

    # Process Assignments
    for asn in all_assignments:
        resolve_id(asn, 'expense_type', ref_expense_types)
        resolve_list(asn, 'tags', ref_tags)

    # 3. Load to BigQuery (Multiple Tables)
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

        # Load tables
        load_table(TABLE_ID, all_expenses)
        load_table(f"{TABLE_ID}_assignments", all_assignments)
        
        # Loading Ref tables is now optional if all IDs are replaced, 
        # but good for completeness/audit.
        load_table('currencies', list(ref_currencies.values()))
        load_table('tags', list(ref_tags.values()))
        load_table('expense_types', list(ref_expense_types.values()))
        load_table('accounts', list(ref_accounts.values()))

        return f"Success: Loaded {len(all_expenses)} expenses and related tables.", 200

    except Exception as e:
        print(f"BigQuery Load Error: {e}")
        return f"BigQuery Load Error: {e}", 500
