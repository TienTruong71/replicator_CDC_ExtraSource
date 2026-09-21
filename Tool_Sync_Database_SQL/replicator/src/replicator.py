import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import time
from dotenv import load_dotenv

try:
    from db_utils import (
        connect_db, ensure_table_exists, get_primary_key,
        upsert_data_odbc, delete_data_odbc,
        sync_schema_direct, fetch_rows_by_pks,
    )
except ImportError:
    from .db_utils import (
        connect_db, ensure_table_exists, get_primary_key,
        upsert_data_odbc, delete_data_odbc,
        sync_schema_direct, fetch_rows_by_pks,
    )

try:
    from setup_triggers import auto_discover_new_tables, setup_triggers, get_monitored_tables, ensure_audit_log_table
    from logger import Logger
except ImportError:
    from .setup_triggers import auto_discover_new_tables, setup_triggers, get_monitored_tables, ensure_audit_log_table
    from .logger import Logger

try:
    from manual_sync import run_manual_sync
except ImportError:
    from .manual_sync import run_manual_sync

load_dotenv()

BATCH_SIZE = int(os.getenv("KINGDOM_BATCH_SIZE", "500"))
POLL_INTERVAL = float(os.getenv("KINGDOM_POLL_INTERVAL", "1.0"))
SCHEMA_CHECK_INTERVAL = float(os.getenv("KINGDOM_SCHEMA_CHECK_INTERVAL", "5.0"))
TABLE_SCAN_INTERVAL = float(os.getenv("KINGDOM_TABLE_SCAN_INTERVAL", "300.0"))


def start_replicator():
    Logger.info("Starting Trigger-based CDC Replicator...")
    prefix = "KINGDOM"

    pk_cache = {}
    table_metadata = {}
    last_discovery_time = 0
    last_heartbeat_time = 0

    while True:
        src_conn = None
        dst_conn = None
        try:
            Logger.info("Initializing database connections...")
            src_conn = connect_db(prefix, target=False)
            dst_conn = connect_db(prefix, target=True)
            Logger.success(
                f"Source: {os.getenv(f'{prefix}_SQLSERVER_DB')} "
                f"-> Target: {os.getenv(f'{prefix}_DST_SQLSERVER_DB')}"
            )

            ensure_audit_log_table(src_conn)

            Logger.success("Replicator main loop active.")
            while True:
                if time.time() - last_discovery_time >= TABLE_SCAN_INTERVAL:
                    Logger.scan("Checking for new tables...")
                    try:
                        new_tables = auto_discover_new_tables(src_conn)
                        if new_tables:
                            Logger.success(f"Auto-setup completed for: {', '.join(new_tables)}")

                        all_monitored = get_monitored_tables(src_conn)
                        for t in all_monitored:
                            if t not in table_metadata:
                                table_metadata[t] = {"last_schema_sync": 0}
                    except Exception as discovery_err:
                        Logger.warn(f"Discovery check failed: {discovery_err}")
                    last_discovery_time = time.time()

                for table, meta in table_metadata.items():
                    if time.time() - meta["last_schema_sync"] >= SCHEMA_CHECK_INTERVAL:
                        ensure_table_exists(src_conn, dst_conn, table)
                        sync_schema_direct(src_conn, dst_conn, "dbo", table)
                        meta["last_schema_sync"] = time.time()

                cursor = src_conn.cursor()
                try:
                    cursor.execute(
                        f"SELECT TOP {BATCH_SIZE} log_id, table_name, pk_value, operation "
                        f"FROM dbo.sync_audit_log ORDER BY log_id"
                    )
                    logs = cursor.fetchall()
                except Exception as e:
                    if "invalid object name" in str(e).lower() or "42S02" in str(e):
                        Logger.warn("Audit log table not found. Attempting auto-setup...")
                        setup_triggers()
                        continue
                    raise e

                try:
                    cursor.execute("SELECT COUNT(*) FROM dbo.sync_audit_log")
                    total_pending = cursor.fetchone()[0]
                except:
                    total_pending = "Unknown"

                if not logs:
                    if time.time() - last_heartbeat_time > 30.0:
                        pending_fmt = f"{total_pending:,}" if isinstance(total_pending, int) else total_pending
                        status = "Idle" if total_pending == 0 else f"Waiting (Pending: {pending_fmt})"
                        Logger.heartbeat(f"Replicator is {status}. Tables watched: {len(table_metadata)}")
                        last_heartbeat_time = time.time()
                    cursor.close()
                    time.sleep(POLL_INTERVAL)
                    continue

                last_heartbeat_time = time.time()
                pending_fmt = f"{total_pending:,}" if isinstance(total_pending, int) else total_pending
                Logger.process(f"Processing batch of {len(logs)} changes (Total pending: {pending_fmt})")

                changes_by_table = {}
                max_log_id = logs[-1][0]

                for log_id, table, pk, op in logs:
                    if table.startswith("sys") or table.startswith("MSr") or table == "sync_audit_log":
                        max_log_id = max(max_log_id, log_id)
                        continue

                    if table not in changes_by_table:
                        changes_by_table[table] = {"I": set(), "U": set(), "D": set()}
                    changes_by_table[table][op].add(pk)

                for table, ops in changes_by_table.items():
                    if table not in table_metadata:
                        table_metadata[table] = {"last_schema_sync": 0}

                    if table not in pk_cache:
                        pk_col = get_primary_key(table, prefix)
                        pk_cache[table] = pk_col if pk_col else "ID"

                    pk_col = pk_cache[table]

                    upsert_pks = ops["I"].union(ops["U"])
                    if upsert_pks:
                        rows = fetch_rows_by_pks(src_conn, "dbo", table, pk_col, list(upsert_pks))
                        if rows:
                            upsert_data_odbc(dst_conn, table, rows, pk_col)

                    for pk in ops["D"]:
                        delete_data_odbc(dst_conn, table, {pk_col: pk}, pk_col)

                for table, ops in changes_by_table.items():
                    Logger.info(f"Table: {table:<25} | Sync: {len(ops['I'])+len(ops['U']):>4} rows | Clean: {len(ops['D']):>4} rows | Status: [OK]", indent=1)

                del_cursor = src_conn.cursor()
                del_cursor.execute(f"DELETE FROM dbo.sync_audit_log WHERE log_id <= {max_log_id}")
                src_conn.commit()
                del_cursor.close()
                cursor.close()
                Logger.success(f"Synced batch up to log_id {max_log_id}")

        except KeyboardInterrupt:
            Logger.info("Replicator stopped by user.")
            break
        except Exception as err:
            Logger.error("Connection lost or database error", exc=err)
            Logger.info("Attempting to reconnect in 10s...")
            try:
                if src_conn: src_conn.close()
                if dst_conn: dst_conn.close()
            except: pass
            time.sleep(10)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trigger-based CDC Replicator")
    parser.add_argument("--sync-missing", action="store_true", help="Find and queue missing rows before starting")
    parser.add_argument("--table", help="Specific table for sync-missing (optional)")
    parser.add_argument("--setup-triggers", action="store_true", help="Setup or update CDC triggers on source database")
    args = parser.parse_args()

    if args.setup_triggers:
        from setup_triggers import setup_triggers
        setup_triggers()
        sys.exit(0)

    if args.sync_missing:
        from manual_sync import run_manual_sync
        run_manual_sync(args.table)

    start_replicator()
