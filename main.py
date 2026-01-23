import os
import functions_framework
import requests
from google.cloud import bigquery
from datetime import datetime
import traceback

# Environment Variables
# These should be set in the Cloud Function configuration
API_KEY = os.environ.get('QUICK_RIPORT_API_KEY')
DATASET_ID = os.environ.get('BQ_DATASET_ID', 'quick_riport_data')
TABLE_ID = os.environ.get('BQ_TABLE_ID', 'expenses')
PROJECT_ID = os.environ.get('GCP_PROJECT') # Automatically set by Cloud Functions

print("MODULE LOADED: Script starting initialization...", flush=True)

@functions_framework.http
def import_expenses(request):
    """HTTP Cloud Function to fetch expenses and load to BigQuery."""
    try:
        print("Starting execution...")
        
        if not API_KEY:
            # Return as 200 OK so we can see the message in the browser/scheduler result
            return "CONFIGURATION ERROR: QUICK_RIPORT_API_KEY is missing. Please set the environment variable.", 200

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
        
        # New containers for linking tables
        all_expense_tags = []
        all_assignment_tags = []
        
        # Reference data (using dicts to deduplicate by ID across pages)
        ref_currencies = {}
        ref_tags = {}
        ref_expense_types = {}
        ref_accounts = {}

        # Initial Request
        next_url = "https://api.quick.riport.co.hu/2/expenses?page_size=200"
        page_count = 0
        
        while next_url:
            page_count += 1
            print(f"Fetching page {page_count}... URL: {next_url}")
            
            response = requests.get(next_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Extract Reference Data (if present on this page)
            results_node = None
            if isinstance(data, dict):
                 if 'results' in data and isinstance(data['results'], dict):
                     results_node = data['results']
                 elif 'expenses' in data: 
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
            print(f"Page {page_count}: Fetched {count} expenses.")
            
            # Get next page URL
            next_url = data.get('next') if isinstance(data, dict) else None
            
            # Safety break
            if page_count > 1000:
                print("Warning: Reached 1000 pages limit.")
                break

        print(f"Total Fetched: Expenses={len(all_expenses)}, Assignments={len(all_assignments)}")

        if len(all_expenses) == 0:
            return "No data to insert.", 200

        # 2. Data Enrichment (ID Resolution Only - NO Tag Flattening)
        print("Enriching data (resolving IDs to names)...")
        
        def resolve_id(obj, field, ref_dict, target_field=None):
            """Replaces ID in 'field' with name from 'ref_dict'."""
            if field in obj and obj[field] is not None:
                ref_id = obj[field]
                if ref_id in ref_dict:
                    obj[target_field or field] = ref_dict[ref_id].get('name')

        # Helper to extract tags to a linking table
        def extract_tags(source_obj, source_id_field, target_list, id_field_name):
            tags_found = set()
            for field in ['tags', 'simple_tags']:
                if field in source_obj and isinstance(source_obj[field], list):
                    for item in source_obj[field]:
                        tag_id = item
                        if isinstance(item, dict) and 'id' in item:
                            tag_id = item['id']
                        
                        if tag_id not in tags_found and source_obj.get(source_id_field):
                             tags_found.add(tag_id)
                             target_list.append({
                                 id_field_name: source_obj[source_id_field],
                                 'tag_id': tag_id
                             })
            
            for field in ['tags', 'simple_tags']:
                if field in source_obj and isinstance(source_obj[field], list):
                     new_list = []
                     for item in source_obj[field]:
                         if isinstance(item, dict) and 'id' in item:
                             new_list.append(item['id'])
                         else:
                             new_list.append(item)
                     source_obj[field] = new_list

        # Process Expenses
        for exp in all_expenses:
            resolve_id(exp, 'currency', ref_currencies)
            resolve_id(exp, 'account', ref_accounts)
            extract_tags(exp, 'id', all_expense_tags, 'expense_id')

        # Process Assignments
        for asn in all_assignments:
            resolve_id(asn, 'expense_type', ref_expense_types)
            extract_tags(asn, 'id', all_assignment_tags, 'assignment_id')
        
        # 3. Load to BigQuery (Multiple Tables)
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
        load_table("expense_tags", all_expense_tags)
        load_table("assignment_tags", all_assignment_tags)
        load_table('currencies', list(ref_currencies.values()))
        load_table('tags', list(ref_tags.values()))
        load_table('expense_types', list(ref_expense_types.values()))
        load_table('accounts', list(ref_accounts.values()))

        return f"Success: Loaded data with linking tables.", 200

    except Exception as e:
        print(f"CRITICAL FAILURE: {e}")
        traceback.print_exc()
        return f"Execution/Load Error: {e}", 500
