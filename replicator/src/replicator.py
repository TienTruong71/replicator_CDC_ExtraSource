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
        get_source_id, claim_source_identity,
        cleanup_processed_audit_log,
    )
except ImportError:
    from .db_utils import (
        connect_db, ensure_table_exists, get_primary_key,
        upsert_data_odbc,
        sync_schema_direct, fetch_rows_by_pks,
        get_source_id, claim_source_identity,
        cleanup_processed_audit_log,
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

try:
    from fk_remap import (
        discover_fk_relationships, topological_order,
        build_parent_id_map, remap_child_fks,
    )
except ImportError:
    from .fk_remap import (
        discover_fk_relationships, topological_order,
        build_parent_id_map, remap_child_fks,
    )


def _row_value_ci(row, col):
    key = None
    for k in row.keys():
        if k.lower() == col.lower():
            key = k
            break
    return row.get(key) if key is not None else None

load_dotenv()

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))
SCHEMA_CHECK_INTERVAL = float(os.getenv("SCHEMA_CHECK_INTERVAL", "5.0"))
TABLE_SCAN_INTERVAL = float(os.getenv("TABLE_SCAN_INTERVAL", "300.0"))


AUDIT_LOG_RETENTION_DAYS = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "7"))
AUDIT_LOG_CLEANUP_INTERVAL = float(os.getenv("AUDIT_LOG_CLEANUP_INTERVAL", "3600.0"))

MAX_FK_DEFER_RETRIES = int(os.getenv("MAX_FK_DEFER_RETRIES", "10"))


def start_replicator():
    Logger.info("Starting Trigger-based CDC Replicator...")

    try:
        from multi_source_config import MultiSourceConfig
    except ImportError:
        from .multi_source_config import MultiSourceConfig

    config_mgr = MultiSourceConfig()
    sources = config_mgr.load_sources()

    if not sources:
        Logger.error("No sources configured. Please check environment variables (SYNC_SOURCES).")
        return

    for source_id, config in sources.items():
        pre_conn = None
        try:
            pre_conn = connect_db(config.prefix, target=True)
            claim_source_identity(pre_conn, source_id, config.host, config.database)
        except RuntimeError as claim_err:
            Logger.error(f"SOURCE_ID conflict for source {source_id}", exc=claim_err)
            return
        finally:
            if pre_conn:
                try: pre_conn.close()
                except: pass

    source_states = {source_id: {'pk_cache': {}, 'table_metadata': {}, 'last_discovery_time': 0} for source_id in sources.keys()}
    last_heartbeat_time = time.time()
    last_cleanup_time = 0.0

    Logger.success("Replicator main loop active.")

    while True:
        try:
            config_mgr.reload_config()
            sources = config_mgr.get_all_sources()

            for source_id, config in sources.items():
                if source_id not in source_states:
                    source_states[source_id] = {'pk_cache': {}, 'table_metadata': {}, 'last_discovery_time': 0, 'audit_log_ensured': False}

                prefix = config.prefix
                excluded = {t.strip() for t in os.getenv(f"{prefix}_EXCLUDE_TABLES", "").split(",") if t.strip()}
                src_conn = None
                dst_conn = None
                try:
                    src_conn = connect_db(prefix, target=False)
                    dst_conn = connect_db(prefix, target=True)

                    state = source_states[source_id]

                    if not state.get('audit_log_ensured', False):
                        ensure_audit_log_table(src_conn)
                        state['audit_log_ensured'] = True

                    if (AUDIT_LOG_RETENTION_DAYS > 0
                            and time.time() - last_cleanup_time >= AUDIT_LOG_CLEANUP_INTERVAL):
                        cleanup_processed_audit_log(src_conn, AUDIT_LOG_RETENTION_DAYS)
                        last_cleanup_time = time.time()

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
                    table_pk_logs = {}
                    processed_log_ids = set()
                    deferred_log_ids = set()

                    for log_id, table, pk, op in logs:
                        if table.startswith("sys") or table.startswith("MSr") or table == "sync_audit_log" or table == "sync_dedup_tracker":
                            processed_log_ids.add(log_id)
                            continue
                        if table in excluded:
                            processed_log_ids.add(log_id)
                            continue

                        if table not in changes_by_table:
                            changes_by_table[table] = {"I": set(), "U": set()}
                            table_pk_logs[table] = {}

                        if op in changes_by_table[table]:
                            changes_by_table[table][op].add(pk)
                        table_pk_logs[table].setdefault(str(pk), []).append(log_id)

                    machine_id = get_source_id()
                    fk_map = discover_fk_relationships(dst_conn, list(changes_by_table.keys()), cache_key=source_id)
                    ordered_tables = topological_order(list(changes_by_table.keys()), fk_map)

                    for table in ordered_tables:
                        ops = changes_by_table[table]
                        if table not in table_metadata:
                            table_metadata[table] = {"last_schema_sync": 0}

                        if table not in pk_cache:
                            pk_col = get_primary_key(table, prefix)
                            pk_cache[table] = pk_col if pk_col else "ID"

                        pk_col = pk_cache[table]
                        pk_logs = table_pk_logs.get(table, {})

                        upsert_pks = ops["I"].union(ops["U"])
                        if not upsert_pks:
                            continue

                        rows = fetch_rows_by_pks(src_conn, "dbo", table, pk_col, list(upsert_pks))
                        deferred_pks = set()

                        if rows:
                            valid_rows = list(rows)
                            for r in valid_rows:
                                r['sync_source_id'] = machine_id

                            links = fk_map.get(table.lower())
                            if config.insert_only and links:
                                id_maps = {}
                                for fk_col, parent_table, parent_pk_col in links:
                                    needed = {_row_value_ci(r, fk_col) for r in valid_rows}
                                    needed.discard(None)
                                    id_maps[parent_table.lower()] = build_parent_id_map(
                                        dst_conn, parent_table, parent_pk_col, machine_id, needed
                                    )
                                ready_rows, deferred_rows = remap_child_fks(valid_rows, links, id_maps)
                                deferred_pks = {str(_row_value_ci(r, pk_col)) for r in deferred_rows}
                                valid_rows = ready_rows
                                if deferred_rows:
                                    Logger.info(
                                        f"[{machine_id}] Table: {table:<25} | Deferred: {len(deferred_rows):>4} rows (parent not on target yet)",
                                        indent=1,
                                    )

                            if valid_rows:
                                upsert_data_odbc(dst_conn, table, valid_rows, pk_col, insert_only=config.insert_only)
                                Logger.info(f"[{machine_id}] Table: {table:<25} | Sync: {len(valid_rows):>4} rows | Status: [OK]", indent=1)

                        for pk_str, ids in pk_logs.items():
                            if pk_str in deferred_pks:
                                deferred_log_ids.update(ids)
                                continue
                            processed_log_ids.update(ids)

                    if processed_log_ids:
                        update_cursor = src_conn.cursor()
                        log_id_list = list(processed_log_ids)
                        chunk_size = 1000
                        for i in range(0, len(log_id_list), chunk_size):
                            chunk = log_id_list[i:i+chunk_size]
                            placeholders = ",".join("?" for _ in chunk)
                            update_cursor.execute(f"UPDATE dbo.sync_audit_log SET status = 'processed', processed_at = GETDATE(), source_id = ? WHERE log_id IN ({placeholders})", [source_id] + chunk)
                        src_conn.commit()
                        update_cursor.close()

                    if deferred_log_ids:
                        defer_cursor = src_conn.cursor()
                        defer_id_list = list(deferred_log_ids)
                        chunk_size = 1000
                        for i in range(0, len(defer_id_list), chunk_size):
                            chunk = defer_id_list[i:i+chunk_size]
                            placeholders = ",".join("?" for _ in chunk)
                            defer_cursor.execute(
                                f"UPDATE dbo.sync_audit_log SET retry_count = retry_count + 1 "
                                f"WHERE log_id IN ({placeholders})",
                                chunk,
                            )
                            defer_cursor.execute(
                                f"UPDATE dbo.sync_audit_log SET status = 'deferred_max', processed_at = GETDATE(), source_id = ? "
                                f"WHERE log_id IN ({placeholders}) AND retry_count >= ?",
                                [source_id] + chunk + [MAX_FK_DEFER_RETRIES],
                            )
                        src_conn.commit()
                        defer_cursor.execute(
                            "SELECT COUNT(*) FROM dbo.sync_audit_log WHERE status = 'deferred_max'"
                        )
                        gave_up = defer_cursor.fetchone()[0]
                        defer_cursor.close()
                        if gave_up:
                            Logger.warn(
                                f"[{source_id}] {gave_up} orphan row(s) parked as 'deferred_max' "
                                f"(parent never arrived after {MAX_FK_DEFER_RETRIES} retries)."
                            )

                    cursor.close()
                    deferred_count = len(deferred_log_ids)
                    if deferred_count > 0:
                        Logger.success(f"[{source_id}] Processed {len(processed_log_ids)} logs, deferred {deferred_count} for next poll")
                    else:
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
        setup_triggers()
        sys.exit(0)

    if args.sync_missing:
        run_manual_sync(args.table)

    start_replicator()

