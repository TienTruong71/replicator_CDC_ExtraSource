import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import time
from dotenv import load_dotenv

try:
    from db_utils import (
        connect_db, ensure_table_exists, get_primary_key,
        upsert_data_odbc,
        sync_schema_direct, fetch_rows_by_pks,
    )
except ImportError:
    from .db_utils import (
        connect_db, ensure_table_exists, get_primary_key,
        upsert_data_odbc,
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

    try:
        from multi_source_config import MultiSourceConfig
        from deduplication_engine import DeduplicationEngine
    except ImportError:
        from .multi_source_config import MultiSourceConfig
        from .deduplication_engine import DeduplicationEngine

    config_mgr = MultiSourceConfig()
    sources = config_mgr.load_sources()

    if not sources:
        Logger.error("No sources configured. Please check environment variables (SYNC_SOURCES).")
        return

    dedup_engine = DeduplicationEngine()

    source_states = {source_id: {'pk_cache': {}, 'table_metadata': {}, 'last_discovery_time': 0} for source_id in sources.keys()}
    last_heartbeat_time = time.time()

    Logger.success("Replicator main loop active.")

    while True:
        try:
            config_mgr.reload_config()
            sources = config_mgr.get_all_sources()

            for source_id, config in sources.items():
                if source_id not in source_states:
                    source_states[source_id] = {'pk_cache': {}, 'table_metadata': {}, 'last_discovery_time': 0, 'audit_log_ensured': False}

                prefix = config.prefix
                src_conn = None
                dst_conn = None
                try:
                    src_conn = connect_db(prefix, target=False)
                    dst_conn = connect_db(prefix, target=True)
                    
                    state = source_states[source_id]

                    if not state.get('audit_log_ensured', False):
                        ensure_audit_log_table(src_conn)
                        state['audit_log_ensured'] = True

                    state = source_states[source_id]
                    pk_cache = state['pk_cache']
                    table_metadata = state['table_metadata']

                    if time.time() - state['last_discovery_time'] >= TABLE_SCAN_INTERVAL:
                        try:
                            new_tables = auto_discover_new_tables(src_conn, prefix=prefix, insert_only=config.insert_only)
                            if new_tables:
                                Logger.success(f"[{source_id}] Auto-setup completed for: {', '.join(new_tables)}")

                            all_monitored = get_monitored_tables(src_conn, prefix=prefix, insert_only=config.insert_only)
                            for t in all_monitored:
                                if t not in table_metadata:
                                    table_metadata[t] = {"last_schema_sync": 0}
                        except Exception as discovery_err:
                            Logger.warn(f"[{source_id}] Discovery check failed: {discovery_err}")
                        state['last_discovery_time'] = time.time()

                    for table, meta in table_metadata.items():
                        if time.time() - meta["last_schema_sync"] >= SCHEMA_CHECK_INTERVAL:
                            ensure_table_exists(src_conn, dst_conn, table)
                            sync_schema_direct(src_conn, dst_conn, "dbo", table)
                            meta["last_schema_sync"] = time.time()

                    cursor = src_conn.cursor()
                    try:
                        cursor.execute(
                            f"SELECT TOP {config.batch_size} log_id, table_name, pk_value, operation "
                            f"FROM dbo.sync_audit_log WHERE status = 'pending' ORDER BY log_id"
                        )
                        logs = cursor.fetchall()
                    except Exception as e:
                        if "invalid object name" in str(e).lower() or "42S02" in str(e):
                            Logger.warn(f"[{source_id}] Audit log table not found. Waiting for setup...")
                            continue
                        raise e

                    try:
                        cursor.execute("SELECT COUNT(*) FROM dbo.sync_audit_log WHERE status = 'pending'")
                        total_pending = cursor.fetchone()[0]
                    except:
                        total_pending = "Unknown"

                    if not logs:
                        if time.time() - last_heartbeat_time > 30.0:
                            pending_fmt = f"{total_pending:,}" if isinstance(total_pending, int) else total_pending
                            status = "Idle" if total_pending == 0 else f"Waiting (Pending: {pending_fmt})"
                            Logger.heartbeat(f"[{source_id}] Replicator is {status}. Tables watched: {len(table_metadata)}")
                            last_heartbeat_time = time.time()
                        cursor.close()
                        continue

                    last_heartbeat_time = time.time()
                    pending_fmt = f"{total_pending:,}" if isinstance(total_pending, int) else total_pending
                    Logger.process(f"[{source_id}] Processing batch of {len(logs)} changes (Total pending: {pending_fmt})")

                    changes_by_table = {}
                    log_ids = []

                    for log_id, table, pk, op in logs:
                        log_ids.append(log_id)
                        if table.startswith("sys") or table.startswith("MSr") or table == "sync_audit_log" or table == "sync_dedup_tracker":
                            continue

                        if table not in changes_by_table:
                            changes_by_table[table] = {"I": set(), "U": set()}

                        op_mapped = "I" if config.insert_only and op == "U" else op
                        if op_mapped in changes_by_table[table]:
                            changes_by_table[table][op_mapped].add(pk)

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
                                valid_rows = []
                                for row in rows:
                                    if config.insert_only:
                                        if dedup_engine.is_duplicate(table, row, source_id):
                                            continue
                                    valid_rows.append(row)

                                if valid_rows:
                                    upsert_data_odbc(dst_conn, table, valid_rows, pk_col)
                                    Logger.info(f"[{source_id}] Table: {table:<25} | Sync: {len(valid_rows):>4} rows | Status: [OK]", indent=1)

                    if log_ids:
                        update_cursor = src_conn.cursor()
                        chunk_size = 1000
                        for i in range(0, len(log_ids), chunk_size):
                            chunk = log_ids[i:i+chunk_size]
                            placeholders = ",".join("?" for _ in chunk)
                            update_cursor.execute(f"UPDATE dbo.sync_audit_log SET status = 'processed', processed_at = GETDATE(), source_id = ? WHERE log_id IN ({placeholders})", [source_id] + chunk)
                        src_conn.commit()
                        update_cursor.close()

                    cursor.close()
                    Logger.success(f"[{source_id}] Synced batch of {len(logs)} logs")

                except Exception as src_err:
                    Logger.error(f"Connection lost or database error for source {source_id}", exc=src_err)
                finally:
                    if src_conn:
                        try: src_conn.close()
                        except: pass
                    if dst_conn:
                        try: dst_conn.close()
                        except: pass

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            Logger.info("Replicator stopped by user.")
            break
        except Exception as err:
            Logger.error("Main loop error", exc=err)
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
