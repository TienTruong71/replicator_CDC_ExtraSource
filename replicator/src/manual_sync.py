import os
import sys
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from db_utils import (
        connect_db, get_primary_key, get_key_columns, get_trigger_key_column,
        ensure_table_exists, sync_schema_direct, get_source_prefix, get_source_id,
    )
    from logger import Logger
except ImportError:
    from .db_utils import (
        connect_db, get_primary_key, get_key_columns, get_trigger_key_column,
        ensure_table_exists, sync_schema_direct, get_source_prefix, get_source_id,
    )
    from .logger import Logger

load_dotenv()

def get_target_pks(conn, table_name, key_cols):
    """Fetch the key of every target row as a set of tuples.

    key_cols is the full row identity, so a composite-key table is compared on
    all of its columns. Comparing on one column alone reported rows as already
    present when only part of their key matched, so real missing rows were
    never queued.
    """
    cursor = conn.cursor()
    Logger.info(f"Fetching all IDs from Target for table {table_name}...")

    pks = set()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')
    select_list = ", ".join(f"[{c}]" for c in key_cols)
    query = f"SELECT {select_list} FROM dbo.[{table_clean}]"

    cursor.execute(query)
    count = 0
    while True:
        rows = cursor.fetchmany(50000)
        if not rows:
            break
        for row in rows:
            pks.add(tuple(str(v) for v in row))
            count += 1
        if count % 250000 == 0:
            Logger.info(f"  > Loaded {count:,} Target IDs...", indent=1)

    Logger.success(f"Loaded {count:,} Target IDs into memory.", indent=1)
    cursor.close()
    return pks


def get_target_source_record_ids(conn, table_name, source_id):
    """Fetch source_record_id values already present on the target for this source."""
    cursor = conn.cursor()
    Logger.info(f"Fetching existing source_record_id from Target for {table_name} (source={source_id})...")

    ids = set()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')

    check_col = """
        SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=? AND COLUMN_NAME='source_record_id'
    """
    cursor.execute(check_col, (table_clean,))
    if cursor.fetchone()[0] == 0:
        Logger.warn(f"  > Target dbo.[{table_clean}] has no source_record_id column yet — treating as empty.", indent=1)
        cursor.close()
        return ids

    query = f"SELECT [source_record_id] FROM dbo.[{table_clean}] WHERE [sync_source_id] = ?"
    cursor.execute(query, (source_id,))
    count = 0
    while True:
        rows = cursor.fetchmany(50000)
        if not rows:
            break
        for row in rows:
            if row[0] is not None:
                ids.add(str(row[0]))
            count += 1
        if count % 250000 == 0:
            Logger.info(f"  > Loaded {count:,} Target source_record_ids...", indent=1)

    Logger.success(f"Loaded {len(ids):,} existing source_record_ids for source {source_id}.", indent=1)
    cursor.close()
    return ids


NUMERIC_PK_TYPES = ("int", "bigint", "smallint", "tinyint", "numeric", "decimal")


def get_source_pk_type(conn, table_name, pk_col):
    """Return the SQL data type of the source PK column, lowercased."""
    cursor = conn.cursor()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')
    cursor.execute(
        "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=? AND COLUMN_NAME=?",
        (table_clean, pk_col),
    )
    row = cursor.fetchone()
    cursor.close()
    return (row[0].lower().strip() if row and row[0] else "")


def get_target_watermark(conn, table_name, source_id):
    """Return the highest numeric source_record_id already on target for this source, else None."""
    cursor = conn.cursor()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')

    cursor.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=? AND COLUMN_NAME='source_record_id'",
        (table_clean,),
    )
    if cursor.fetchone()[0] == 0:
        cursor.close()
        return None

    cursor.execute(
        f"SELECT MAX(CAST([source_record_id] AS BIGINT)) FROM dbo.[{table_clean}] "
        f"WHERE [sync_source_id] = ? AND [source_record_id] IS NOT NULL",
        (source_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row and row[0] is not None else None


def queue_missing_by_watermark(src_conn, audit_conn, table_name, pk_col, watermark):
    """Queue source rows whose numeric PK is above the target watermark. O(1) memory."""
    src_cursor = src_conn.cursor()
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')

    if watermark is None:
        src_cursor.execute(f"SELECT [{pk_col}] FROM dbo.[{table_clean}]")
        Logger.info(f"No watermark for {table_clean} — queueing all source rows.")
    else:
        src_cursor.execute(
            f"SELECT [{pk_col}] FROM dbo.[{table_clean}] WHERE [{pk_col}] > ?",
            (watermark,),
        )
        Logger.info(f"Watermark for {table_clean} = {watermark}; queueing rows above it.")

    missing_pks = []
    total = 0
    while True:
        rows = src_cursor.fetchmany(50000)
        if not rows:
            break
        for row in rows:
            missing_pks.append(str(row[0]))
            total += 1
            if len(missing_pks) >= 50000:
                inject_to_audit_log(audit_conn, table_name, missing_pks)
                missing_pks = []
        if total % 250000 == 0:
            Logger.info(f"  > Queued {total:,} rows...", indent=1)

    if missing_pks:
        inject_to_audit_log(audit_conn, table_name, missing_pks)

    Logger.success(f"Completed! Queued {total:,} rows above watermark for {table_clean}.")
    src_cursor.close()


def find_and_queue_missing(src_conn, dst_conn, audit_conn, table_name):
    """Find missing rows and insert them into sync_audit_log."""
    prefix = get_source_prefix()

    audit_col = get_trigger_key_column(table_name, prefix) or get_primary_key(table_name, prefix)
    if not audit_col:
        Logger.error(f"Could not find PK for table {table_name}. Skipping.")
        return
    pk_col = audit_col

    ensure_table_exists(src_conn, dst_conn, table_name)
    table_clean = table_name.replace('[', '').replace(']', '').replace('dbo.', '')
    sync_schema_direct(src_conn, dst_conn, "dbo", table_clean)

    insert_only = os.getenv(f"{prefix}_INSERT_ONLY", "false").lower() in ("true", "1", "yes", "on")

    if insert_only:
        source_id = get_source_id()
        pk_type = get_source_pk_type(src_conn, table_name, pk_col)
        if pk_type in NUMERIC_PK_TYPES:
            watermark = get_target_watermark(dst_conn, table_name, source_id)
            queue_missing_by_watermark(src_conn, audit_conn, table_name, pk_col, watermark)
            return
        Logger.warn(
            f"PK '{pk_col}' of {table_clean} is non-numeric ({pk_type}); "
            f"falling back to in-memory diff. Large non-numeric tables may exhaust RAM."
        )
        target_pks = get_target_source_record_ids(dst_conn, table_name, source_id)
        key_cols = [audit_col]
        compare_tuples = False
    else:
        key_cols = get_key_columns(table_name, prefix)
        if not key_cols:
            key_cols = [audit_col]
            Logger.warn(
                f"{table_clean} has no PK or unique index — comparing on [{audit_col}] only; "
                f"rows that share that value will look already present."
            )
        elif len(key_cols) > 1:
            Logger.info(
                f"{table_clean} has a composite key ({', '.join(key_cols)}) — "
                f"comparing on all {len(key_cols)} columns.",
                indent=1,
            )
        target_pks = get_target_pks(dst_conn, table_name, key_cols)
        compare_tuples = True

    if compare_tuples:
        select_cols = list(key_cols)
        lowered = [c.lower() for c in select_cols]
        if audit_col.lower() in lowered:
            audit_pos = lowered.index(audit_col.lower())
        else:
            select_cols.append(audit_col)
            audit_pos = len(select_cols) - 1
        cmp_len = len(key_cols)
    else:
        select_cols = [audit_col]
        audit_pos = 0
        cmp_len = 1

    src_cursor = src_conn.cursor()
    select_list = ", ".join(f"[{c}]" for c in select_cols)
    src_query = f"SELECT {select_list} FROM dbo.[{table_clean}]"
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
            if compare_tuples:
                present = tuple(str(v) for v in row[:cmp_len]) in target_pks
            else:
                present = str(row[0]) in target_pks

            if not present:
                missing_pks.append(str(row[audit_pos]))
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

    sql = "INSERT INTO dbo.sync_audit_log (table_name, pk_value, operation, status) VALUES (?, ?, 'I', 'pending')"
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
    prefix = get_source_prefix()
    Logger.info("Starting Manual Differential Sync...")

    src_conn = connect_db(prefix, target=False)
    dst_conn = connect_db(prefix, target=True)
    audit_conn = connect_db(prefix, target=False)

    from setup_triggers import ensure_audit_log_table
    ensure_audit_log_table(audit_conn)

    try:
        if specific_table:
            tables = [specific_table]
        else:
            from setup_triggers import get_monitored_tables
            insert_only = os.getenv(f"{prefix}_INSERT_ONLY", "false").lower() == "true"
            tables = get_monitored_tables(src_conn, prefix=prefix, insert_only=insert_only)

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

def force_full_resync(table_name=None):
    """Force full resync by clearing audit log and re-queuing all missing records."""
    prefix = get_source_prefix()
    Logger.info("Starting FORCE FULL RESYNC...")
    
    src_conn = connect_db(prefix, target=False)
    dst_conn = connect_db(prefix, target=True)
    audit_conn = connect_db(prefix, target=False)
    
    try:
        cursor = audit_conn.cursor()
        if table_name:
            cursor.execute("DELETE FROM dbo.sync_audit_log WHERE table_name = ?", (table_name,))
            Logger.info(f"Cleared existing audit log for table: {table_name}")
            run_manual_sync(table_name)
        else:
            cursor.execute("DELETE FROM dbo.sync_audit_log")
            Logger.info("Cleared entire audit log")
            run_manual_sync()
            
        audit_conn.commit()
    except Exception as e:
        audit_conn.rollback()
        Logger.error("Force full resync failed", exc=e)
    finally:
        cursor.close()
        src_conn.close()
        dst_conn.close()
        audit_conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Manual Differential Sync for Missing Rows")
    parser.add_argument("--table", help="Specific table to sync (optional)")
    parser.add_argument("--force", action="store_true", help="Force full resync by clearing existing queued items")
    args = parser.parse_args()

    if args.force:
        force_full_resync(args.table)
    else:
        run_manual_sync(args.table)
