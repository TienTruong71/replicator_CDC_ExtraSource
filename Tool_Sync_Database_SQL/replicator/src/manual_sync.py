import os
import sys
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from db_utils import connect_db, get_primary_key, ensure_table_exists, sync_schema_direct
    from logger import Logger
except ImportError:
    from .db_utils import connect_db, get_primary_key, ensure_table_exists, sync_schema_direct
    from .logger import Logger

load_dotenv()

def get_target_pks(conn, table_name, pk_col):
    """Fetch all PKs from target database into a set."""
    cursor = conn.cursor()
    Logger.info(f"Fetching all IDs from Target for table {table_name}...")

    pks = set()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')
    query = f"SELECT [{pk_col}] FROM dbo.[{table_clean}]"

    cursor.execute(query)
    count = 0
    while True:
        rows = cursor.fetchmany(50000)
        if not rows:
            break
        for row in rows:
            pks.add(str(row[0]))
            count += 1
        if count % 250000 == 0:
            Logger.info(f"  > Loaded {count:,} Target IDs...", indent=1)

    Logger.success(f"Loaded {count:,} Target IDs into memory.", indent=1)
    cursor.close()
    return pks

def find_and_queue_missing(src_conn, dst_conn, audit_conn, table_name):
    """Find missing rows and insert them into sync_audit_log."""
    prefix = "KINGDOM"
    pk_col = get_primary_key(table_name, prefix)
    if not pk_col:
        Logger.error(f"Could not find PK for table {table_name}. Skipping.")
        return


    ensure_table_exists(src_conn, dst_conn, table_name)
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')
    sync_schema_direct(src_conn, dst_conn, "dbo", table_clean)

    target_pks = get_target_pks(dst_conn, table_name, pk_col)

    src_cursor = src_conn.cursor()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')
    src_query = f"SELECT [{pk_col}] FROM dbo.[{table_clean}]"

    src_cursor.execute(src_query)
    missing_pks = []
    total_scanned = 0
    total_missing = 0

    Logger.info(f"Scanning Source IDs and comparing with Target...")

    while True:
        rows = src_cursor.fetchmany(50000)
        if not rows:
            break

        for row in rows:
            total_scanned += 1
            pk_val = str(row[0])
            if pk_val not in target_pks:
                missing_pks.append(pk_val)
                total_missing += 1

            if len(missing_pks) >= 50000:
                inject_to_audit_log(audit_conn, table_name, missing_pks)
                missing_pks = []

        if total_scanned % 250000 == 0:
            Logger.info(f"  > Scanned {total_scanned:,} Source rows... (Found {total_missing:,} missing)", indent=1)

    if missing_pks:
        inject_to_audit_log(audit_conn, table_name, missing_pks)

    Logger.success(f"Completed! Scanned {total_scanned:,} rows. Found and queued {total_missing:,} missing rows.")
    src_cursor.close()

def inject_to_audit_log(conn, table_name, pks):
    """Insert missing PKs into sync_audit_log in bulk."""
    cursor = conn.cursor()
    cursor.fast_executemany = True
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')

    sql = "INSERT INTO dbo.sync_audit_log (table_name, pk_value, operation) VALUES (?, ?, 'I')"
    params = [(table_clean, pk) for pk in pks]

    try:
        t0 = time.time()
        cursor.executemany(sql, params)
        conn.commit()
        if len(pks) >= 5000:
            Logger.info(f"  > Bulk Inserted {len(pks):,} missing IDs into audit_log in {time.time()-t0:.2f}s", indent=2)
    except Exception as e:
        conn.rollback()
        Logger.error(f"Failed to inject batch into audit log", exc=e)
    finally:
        cursor.close()

def run_manual_sync(specific_table=None):
    prefix = "KINGDOM"
    Logger.info("Starting Manual Differential Sync...")

    src_conn = connect_db(prefix, target=False)
    dst_conn = connect_db(prefix, target=True)
    audit_conn = connect_db(prefix, target=False)

    try:
        if specific_table:
            tables = [specific_table]
        else:
            from setup_triggers import get_monitored_tables
            tables = get_monitored_tables(src_conn)

        if not tables:
            Logger.warn("No monitored tables found to sync.")
            return

        for table in tables:
            Logger.process(f"Checking table: {table}")
            find_and_queue_missing(src_conn, dst_conn, audit_conn, table)

    finally:
        src_conn.close()
        dst_conn.close()
        audit_conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Manual Differential Sync for Missing Rows")
    parser.add_argument("--table", help="Specific table to sync (optional)")
    args = parser.parse_args()

    run_manual_sync(args.table)
