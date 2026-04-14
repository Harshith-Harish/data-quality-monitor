"""
Power BI Python Scripts - Direct SQLite Connection

How to use:
    1. Open Power BI Desktop
    2. Go to Get Data → Python script
    3. Paste ONE script per table (4 total)
    4. Power BI will detect the DataFrame and import it
    5. Click Refresh anytime to pull latest data

IMPORTANT: Update DB_PATH below to your actual database path.
Use the full absolute path, e.g.:
    Windows: C:\\Users\\YourName\\Documents\\data_quality\\db\\quality_results.db
    Mac:     /Users/YourName/data_quality/db/quality_results.db

After importing all 4 tables, create relationships in Model view:
    runs.run_id  →  check_results.run_id
    runs.run_id  →  flagged_records.run_id
    runs.run_id  →  column_profiles.run_id
"""

# ============================================================

import sqlite3
import pandas as pd

DB_PATH = r"C:\Users\iamha\Documents\Personal_Projects\data_quality\db\quality_results.db"

conn = sqlite3.connect(DB_PATH)
runs = pd.read_sql("SELECT * FROM runs", conn)
check_results = pd.read_sql("SELECT * FROM check_results", conn)
flagged_records = pd.read_sql("SELECT * FROM flagged_records", conn)
column_profiles = pd.read_sql("SELECT * FROM column_profiles", conn)

conn.close()