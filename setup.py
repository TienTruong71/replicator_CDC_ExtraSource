import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'replicator', 'src'))

from db_utils import connect_db, get_source_prefix

def setup_triggers():
    try:
        print("Setting up CDC triggers...")
        from setup_triggers import setup_triggers
        setup_triggers()
        print("CDC triggers setup completed successfully!")
        return True
    except Exception as e:
        print(f"Failed to setup triggers: {e}")
        return False

def sync_missing(table=None):
    try:
        print("Syncing existing data from source to target...")
        if table:
            print(f"Syncing table: {table}")
        else:
            print("Syncing all configured tables")

        from manual_sync import run_manual_sync
        run_manual_sync(table)
        print("Initial data sync completed successfully!")
        return True
    except Exception as e:
        print(f"Failed to sync existing data: {e}")
        return False


def validate_schemas():
    """Validate schemas across multiple sources for conflicts."""
    try:
        print("Validating table schemas across sources...")
        from schema_validator import SchemaValidator
        from dotenv import load_dotenv

        load_dotenv()

        validator = SchemaValidator()

        from multi_source_config import MultiSourceConfig
        config_mgr = MultiSourceConfig()
        sources = config_mgr.load_sources()

        if len(sources) < 2:
            print("  Schema validation requires at least 2 sources.")
            print(f"   Current sources: {len(sources)}")
            return True

        table_sources = {}

        for source_id, config in sources.items():
            try:
                conn = connect_db(config.prefix, target=False)
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'dbo'
                    AND TABLE_NAME NOT LIKE 'sys%' AND TABLE_NAME != 'sync_audit_log'
                """)

                for (table_name,) in cursor.fetchall():
                    if table_name not in table_sources:
                        table_sources[table_name] = []
                    table_sources[table_name].append((source_id, conn, 'dbo'))

            except Exception as e:
                print(f"  Could not analyze source {source_id}: {e}")

        multi_source_tables = {name: srcs for name, srcs in table_sources.items() if len(srcs) > 1}

        if not multi_source_tables:
            print("No tables found in multiple sources - no conflicts possible.")
            return True

        print(f"Found {len(multi_source_tables)} tables in multiple sources:")
        for table_name, srcs in multi_source_tables.items():
            source_names = [s[0] for s in srcs]
            print(f"  {table_name}: {', '.join(source_names)}")

        print()

        has_critical = False
        for table_name, srcs in multi_source_tables.items():
            conflicts = validator.validate_multi_source_table(table_name, srcs)
            if any(c.severity == 'CRITICAL' for c in conflicts):
                has_critical = True

        validator.print_summary()

        if has_critical:
            print("\nCRITICAL schema conflicts found!")
            print("   These must be resolved before running multi-source sync.")
            return False
        else:
            print("\nSchema validation passed - safe for multi-source sync.")
            return True

    except Exception as e:
        print(f"Schema validation failed: {e}")
        return False


def check_dependencies():
    missing = []

    try:
        import pyodbc
        print("pyodbc: OK")
    except ImportError:
        missing.append("pyodbc")
        print("pyodbc: Missing")

    try:
        from dotenv import load_dotenv
        print("python-dotenv: OK")
    except ImportError:
        missing.append("python-dotenv")
        print("python-dotenv: Missing")

    if missing:
        print(f"Please install missing dependencies:")
        print(f"pip install {' '.join(missing)}")
        return False

    return True

def test_connection():
    try:
        print("Testing database connection...")
        from dotenv import load_dotenv
        load_dotenv()
        prefix = get_source_prefix()
        print(f"Using source prefix: {prefix}")

        src_conn = connect_db(prefix, target=False)
        print("Source database connection: OK")
        src_conn.close()

        dst_conn = connect_db(prefix, target=True)
        print("Target database connection: OK")
        dst_conn.close()

        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False

def run_replicator():
    try:
        print("Starting replicator...")
        from replicator import start_replicator
        start_replicator()
    except KeyboardInterrupt:
        print("Replicator stopped by user")
    except Exception as e:
        print(f"Replicator failed: {e}")

def show_status():
    try:
        from dotenv import load_dotenv
        load_dotenv()
        prefix = get_source_prefix()

        conn = connect_db(prefix, target=False)
        cursor = conn.cursor()

        print("System Status:")
        print("=" * 50)

        try:
            cursor.execute("SELECT COUNT(*) FROM dbo.sync_audit_log")
            total = cursor.fetchone()[0]
            print(f"Total audit logs: {total:,}")

            cursor.execute("SELECT COUNT(*) FROM dbo.sync_audit_log WHERE status = 'pending'")
            pending = cursor.fetchone()[0]
            print(f"Pending logs: {pending:,}")

            cursor.execute("SELECT COUNT(*) FROM dbo.sync_audit_log WHERE status = 'processed'")
            processed = cursor.fetchone()[0]
            print(f"Processed logs: {processed:,}")

        except Exception as e:
            print(f"Audit log status: Error ({e})")

        try:
            cursor.execute("""
                SELECT COUNT(*) FROM sys.triggers t
                WHERE t.name LIKE 'trig_cdc_%'
            """)
            trigger_count = cursor.fetchone()[0]
            print(f"CDC triggers: {trigger_count}")

            if trigger_count > 0:
                cursor.execute("""
                    SELECT OBJECT_NAME(t.parent_id) as table_name
                    FROM sys.triggers t
                    WHERE t.name LIKE 'trig_cdc_%'
                    GROUP BY t.parent_id
                """)
                tables = [row[0] for row in cursor.fetchall()]
                print(f"Tables with triggers: {', '.join(tables)}")

        except Exception as e:
            print(f"Trigger status: Error ({e})")

        # Check source vs target data counts
        try:
            print("\nData Comparison:")
            print("-" * 30)

            import os
            sync_tables = os.getenv(f"{prefix}_SYNC_TABLES", "")
            if sync_tables:
                tables = [t.strip() for t in sync_tables.split(",")]

                dst_conn = connect_db(prefix, target=True)
                dst_cursor = dst_conn.cursor()

                for table in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                        src_count = cursor.fetchone()[0]

                        try:
                            dst_cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                            dst_count = dst_cursor.fetchone()[0]
                        except:
                            dst_count = 0

                        status = "SYNCED" if src_count == dst_count else "NEEDS SYNC"
                        print(f"{table}: Source={src_count}, Target={dst_count} [{status}]")

                    except Exception as e:
                        print(f"{table}: Error checking counts ({e})")

                dst_conn.close()

        except Exception as e:
            print(f"Data comparison error: {e}")

        conn.close()

    except Exception as e:
        print(f"Failed to get status: {e}")

def main():
    parser = argparse.ArgumentParser(description="Multi-Source CDC Replicator Setup")

    parser.add_argument("--check", action="store_true", help="Check dependencies and connections")
    parser.add_argument("--setup-triggers", action="store_true", help="Setup CDC triggers")
    parser.add_argument("--sync-missing", action="store_true", help="Sync existing data from source")
    parser.add_argument("--table", help="Specific table for sync-missing")
    parser.add_argument("--test-connection", action="store_true", help="Test database connections")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--run", action="store_true", help="Run the replicator")
    parser.add_argument("--validate-schemas", action="store_true", help="Validate table schemas across multiple sources")

    args = parser.parse_args()

    if not any([args.check, args.setup_triggers, args.sync_missing, args.test_connection, args.status, args.run, args.validate_schemas]):
        print("Multi-Source CDC Replicator")
        print("=" * 40)
        print("Usage examples:")
        print("  python setup.py --check                    # Check system")
        print("  python setup.py --setup-triggers           # Setup CDC triggers")
        print("  python setup.py --sync-missing             # Sync existing data")
        print("  python setup.py --sync-missing --table db_test_1  # Sync specific table")
        print("  python setup.py --status                   # Show status")
        print("  python setup.py --validate-schemas         # Validate multi-source schemas")
        print("  python setup.py --run                      # Run continuous sync")
        print("")
        print("Complete workflow:")
        print("  1. python setup.py --check")
        print("  2. python setup.py --setup-triggers")
        print("  3. python setup.py --sync-missing")
        print("  4. python setup.py --run")
        return

    print("Multi-Source CDC Replicator")
    print("=" * 40)

    if args.check:
        print("Checking dependencies...")
        deps_ok = check_dependencies()

        if deps_ok:
            print("Testing connections...")
            conn_ok = test_connection()

            if conn_ok:
                print("All checks passed!")
            else:
                print("Connection check failed.")
        else:
            print("Please install missing dependencies first.")

    elif args.setup_triggers:
        if not check_dependencies():
            print("Dependencies missing. Run --check first.")
            return

        success = setup_triggers()
        if success:
            print("Next steps:")
            print("1. python setup.py --sync-missing  # Sync existing data")
            print("2. python setup.py --run           # Start continuous sync")

    elif args.sync_missing:
        if not check_dependencies():
            print("Dependencies missing. Run --check first.")
            return

        success = sync_missing(args.table)
        if success:
            print("Next: python setup.py --run  # Start continuous sync")

    elif args.test_connection:
        test_connection()

    elif args.status:
        show_status()

    elif args.validate_schemas:
        success = validate_schemas()
        if not success:
            print("Schema validation failed!")
        return

    elif args.run:
        if not check_dependencies():
            print("Dependencies missing. Run --check first.")
            return
        run_replicator()

if __name__ == "__main__":
    main()
