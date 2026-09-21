import os
import sys

_src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replicator", "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from dotenv import load_dotenv
load_dotenv()

try:
    from db_utils import connect_db
except ImportError as e:
    print(f"Could not import db_utils: {e}")
    sys.exit(1)

def check_truncation():
    print("Checking for column size mismatches between source and target...")
    prefix = "KINGDOM"

    src_conn = connect_db(prefix, target=False)
    dst_conn = connect_db(prefix, target=True)

    tables = ['dimension_data', 'dimension_detail_data', 'dimension_detail_data_new']

    src_cursor = src_conn.cursor()
    dst_cursor = dst_conn.cursor()

    found_issue = False

    for table in tables:
        print(f"\n--- Checking table: {table} ---")
        dst_cursor.execute(f"""
            SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table}'
              AND DATA_TYPE IN ('varchar', 'nvarchar', 'char', 'nchar')
        """)
        target_limits = {r[0].lower(): r[1] for r in dst_cursor.fetchall() if r[1] is not None and r[1] > 0}

        if not target_limits:
            print("  (no string columns with fixed length found in target)")
            continue

        for col, limit in target_limits.items():
            try:
                src_cursor.execute(f"SELECT MAX(LEN([{col}])) FROM dbo.[{table}] WHERE [{col}] IS NOT NULL")
                row = src_cursor.fetchone()
                max_len = row[0] if row else None
                if max_len and max_len > limit:
                    found_issue = True
                    print(f"  [OVERFLOW] Column: '{col}'  |  Source max length: {max_len}  |  Target limit: {limit}")
                    print(f"    => Fix: ALTER TABLE dbo.[{table}] ALTER COLUMN [{col}] NVARCHAR({max_len + 50});")
                else:
                    print(f"  [OK]       Column: '{col}'  |  Source max: {max_len or 0}  |  Target limit: {limit}")
            except Exception as e:
                print(f"  [SKIP] Column '{col}': {e}")

    print()
    if not found_issue:
        print("All columns are within target limits. No truncation issues found.")
    else:
        print("DONE. Please run the ALTER TABLE statements above on the Dimension (target) DB before syncing.")

    src_conn.close()
    dst_conn.close()

if __name__ == "__main__":
    check_truncation()
