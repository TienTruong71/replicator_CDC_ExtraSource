import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'replicator', 'src'))

from db_utils import connect_db, get_source_prefix
from dotenv import load_dotenv
from setup_triggers import setup_triggers
from manual_sync import run_manual_sync
from replicator import start_replicator

def check_setup_status():
    """Check if system is already set up"""
    try:
        load_dotenv()

        conn = connect_db(get_source_prefix(), target=False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM sys.triggers t
            WHERE t.name LIKE 'trig_cdc_%'
        """)
        trigger_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM sys.columns
            WHERE object_id = OBJECT_ID('dbo.sync_audit_log')
            AND name IN ('status', 'source_id', 'processed_at')
        """)
        column_count = cursor.fetchone()[0]

        conn.close()

        is_setup = trigger_count > 0 and column_count >= 3
        return is_setup, trigger_count

    except Exception as e:
        print(f"Setup check failed: {e}")
        return False, 0

def auto_setup():
    """Perform automatic setup if needed"""
    try:
        print("Checking system setup status...")
        is_setup, trigger_count = check_setup_status()

        if is_setup:
            print(f"System already setup (Found {trigger_count} triggers). Skipping setup.")
            return True

        print("System not setup. Starting auto setup...")

        print("Step 1: Setting up CDC triggers...")
        setup_triggers()
        print("CDC triggers setup completed.")

        print("Step 2: Checking if initial sync needed...")
        needs_sync = check_initial_sync_needed()

        if needs_sync:
            print("Initial sync needed. Starting background sync...")
            perform_initial_sync()
        else:
            print("No initial sync needed.")

        print("Auto setup completed successfully!")
        return True

    except Exception as e:
        print(f"Auto setup failed: {e}")
        return False

def check_initial_sync_needed():
    """Check if initial sync is needed by comparing source vs target counts"""
    try:
        if os.getenv("SKIP_INITIAL_SYNC", "false").lower() in ("true", "1", "yes", "on"):
            print("SKIP_INITIAL_SYNC is set. Skipping initial sync; relying on triggers only.")
            return False

        prefix = get_source_prefix()
        sync_tables = os.getenv(f"{prefix}_SYNC_TABLES", "")
        if not sync_tables:
            return False

        tables = [t.strip() for t in sync_tables.split(",")]

        src_conn = connect_db(prefix, target=False)
        dst_conn = connect_db(prefix, target=True)

        src_cursor = src_conn.cursor()
        dst_cursor = dst_conn.cursor()

        needs_sync = False

        for table in tables:
            try:

                src_cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                src_count = src_cursor.fetchone()[0]


                try:
                    dst_cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                    dst_count = dst_cursor.fetchone()[0]
                except:
                    dst_count = 0

                insert_only = os.getenv(f"{prefix}_INSERT_ONLY", "false").lower() in ("true", "1", "yes", "on")
                if insert_only:
                    print(f"Table {table}: Source={src_count:,} [INSERT_ONLY mode - will queue all for dedup check]")
                    needs_sync = True
                elif src_count > dst_count:
                    needs_sync = True

            except Exception as e:
                print(f"Error checking {table}: {e}")

        src_conn.close()
        dst_conn.close()

        return needs_sync

    except Exception as e:
        print(f"Initial sync check failed: {e}")
        return False

def perform_initial_sync():
    """Perform initial sync in background with progress"""
    try:
        print("Starting initial data sync...")
        print("This may take several minutes for large datasets...")


        run_manual_sync(None)

        print("Initial sync completed.")

    except Exception as e:
        print(f"Initial sync failed: {e}")

def auto_run():
    """Auto setup and run replicator"""
    print("=" * 60)
    print("Multi-Source CDC Replicator - Auto Setup & Run")
    print("=" * 60)


    setup_success = auto_setup()
    if not setup_success:
        print("Setup failed. Cannot continue.")
        return False


    print("\nFinal Status Check:")
    print("-" * 30)
    show_final_status()


    print("\nStarting continuous replicator...")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    try:
        start_replicator()
    except KeyboardInterrupt:
        print("\nReplicator stopped by user.")
    except Exception as e:
        print(f"Replicator error: {e}")

    return True

def show_final_status():
    """Show final system status"""
    try:
        prefix = get_source_prefix()
        conn = connect_db(prefix, target=False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM sys.triggers t
            WHERE t.name LIKE 'trig_cdc_%'
        """)
        trigger_count = cursor.fetchone()[0]
        print(f"CDC Triggers: {trigger_count}")


        sync_tables = os.getenv(f"{prefix}_SYNC_TABLES", "")
        if sync_tables:
            tables = [t.strip() for t in sync_tables.split(",")]
            dst_conn = connect_db(prefix, target=True)
            dst_cursor = dst_conn.cursor()

            print("Data Status:")
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                    src_count = cursor.fetchone()[0]

                    try:
                        dst_cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                        dst_count = dst_cursor.fetchone()[0]
                    except:
                        dst_count = 0

                    status = "SYNCED" if src_count == dst_count else "PARTIAL"
                    print(f"  {table}: {dst_count:,}/{src_count:,} [{status}]")

                except Exception as e:
                    print(f"  {table}: Error ({e})")

            dst_conn.close()

        conn.close()

    except Exception as e:
        print(f"Status check error: {e}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        print("Manual mode - use setup.py for step-by-step control")
        return

    auto_run()

if __name__ == "__main__":
    main()
