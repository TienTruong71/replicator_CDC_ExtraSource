"""
Initial Sync Tool - Auto Mode with Schema Validation
Sync existing data before starting CDC Replicator - Fully Automated
"""

import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'replicator', 'src'))

from db_utils import connect_db, get_source_prefix

def check_dependencies():
    """Check if required dependencies are installed"""
    missing = []

    try:
        import pyodbc
        print("[OK] pyodbc available")
    except ImportError:
        missing.append("pyodbc")
        print("[ERROR] pyodbc missing")

    try:
        from dotenv import load_dotenv
        print("[OK] python-dotenv available")
    except ImportError:
        missing.append("python-dotenv")
        print("[ERROR] python-dotenv missing")

    if missing:
        print(f"[FATAL] Missing dependencies: {', '.join(missing)}")
        print(f"[FATAL] Run: pip install {' '.join(missing)}")
        return False

    return True

def test_connections():
    """Test database connections"""
    try:
        from db_utils import connect_db
        from dotenv import load_dotenv
        load_dotenv()

        prefix = get_source_prefix()
        print(f"[INFO] Using source prefix: {prefix}")

        # Test source connection
        src_conn = connect_db(prefix, target=False)
        print("[OK] Source database connected")
        src_conn.close()

        # Test target connection
        dst_conn = connect_db(prefix, target=True)
        print("[OK] Target database connected")
        dst_conn.close()

        return True
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e}")
        return False

def check_system_setup():
    """Check if CDC triggers are properly set up"""
    try:
        from db_utils import connect_db

        conn = connect_db(get_source_prefix(), target=False)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM sys.triggers t
            WHERE t.name LIKE 'trig_cdc_%'
        """)
        trigger_count = cursor.fetchone()[0]

        conn.close()

        if trigger_count == 0:
            print("[ERROR] No CDC triggers found!")
            print("[ERROR] Please run CDC trigger setup first")
            return False

        print(f"[OK] CDC triggers found: {trigger_count}")
        return True

    except Exception as e:
        print(f"[ERROR] System setup check failed: {e}")
        return False

def validate_schemas():
    """Validate SOURCE vs TARGET schema compatibility for all configured tables."""
    try:
        print("[INFO] Validating table structure (column names and count)...")

        from simple_column_validator import SimpleColumnValidator
        from db_utils import connect_db
        import os

        # Get configured tables
        prefix = get_source_prefix()
        sync_tables = os.getenv(f"{prefix}_SYNC_TABLES", "")
        if not sync_tables:
            print("[ERROR] No SYNC_TABLES configured in .env file")
            return False

        tables = [t.strip() for t in sync_tables.split(",")]
        print(f"[INFO] Tables to validate: {', '.join(tables)}")

        # Connect to databases
        src_conn = connect_db(prefix, target=False)  # Source
        dst_conn = connect_db(prefix, target=True)   # Target

        # Validate each table
        validator = SimpleColumnValidator()
        all_compatible = True

        for table_name in tables:
            print(f"[INFO] Validating table: {table_name}")
            if not validator.validate_table(src_conn, dst_conn, table_name):
                all_compatible = False

        # Cleanup
        src_conn.close()
        dst_conn.close()

        if all_compatible:
            print("[OK] All table schemas are compatible")
            return True
        else:
            print("[ERROR] Schema validation failed - critical issues found")
            print("[ERROR] Issues found:")
            for issue in validator.issues:
                print(f"[ERROR]   • {issue}")
            return False

    except Exception as e:
        print(f"[ERROR] Schema validation failed: {e}")
        return False

def check_audit_log_status():
    """Check how many records are queued in audit log"""
    try:
        from db_utils import connect_db

        conn = connect_db(get_source_prefix(), target=False)  # Audit_log at source DB
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'pending'")
        pending = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'processed'")
        processed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sync_audit_log")
        total = cursor.fetchone()[0]

        conn.close()

        print(f"[INFO] Audit Log Status: Total={total:,}, Pending={pending:,}, Processed={processed:,}")
        return pending, processed

    except Exception as e:
        print(f"[ERROR] Failed to check audit log: {e}")
        return 0, 0

def perform_initial_sync():
    """Perform initial sync for all tables that need it"""
    try:
        print("\n" + "="*60)
        print("INITIAL SYNC PROCESS")
        print("="*60)

        from manual_sync import run_manual_sync

        start_time = time.time()

        # Run sync for all configured tables
        run_manual_sync(None)

        duration = time.time() - start_time

        print(f"\n[SUCCESS] Initial sync completed in {duration:.1f} seconds")
        return True

    except Exception as e:
        print(f"[ERROR] Initial sync failed: {e}")
        return False

def main():
    print("="*70)
    print("INITIAL SYNC TOOL - AUTO MODE")
    print("="*70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 1: Dependencies
    print("\n[STEP 1] Checking dependencies...")
    if not check_dependencies():
        print("\n[FATAL] Dependencies check failed!")
        input("Press Enter to exit...")
        return False

    # Step 2: Connections
    print("\n[STEP 2] Testing connections...")
    if not test_connections():
        print("\n[FATAL] Connection test failed!")
        input("Press Enter to exit...")
        return False

    # Step 3: System setup
    print("\n[STEP 3] Checking CDC setup...")
    if not check_system_setup():
        print("\n[FATAL] CDC setup incomplete!")
        input("Press Enter to exit...")
        return False

    # Step 4: Schema validation
    print("\n[STEP 4] Validating schemas...")
    if not validate_schemas():
        print("\n[FATAL] Schema validation failed!")
        print("[FATAL] Please resolve schema conflicts before proceeding")
        input("Press Enter to exit...")
        return False

    # Step 5: Running initial sync
    print("\n[STEP 5] Running initial sync...")
    if not perform_initial_sync():
        print("\n[FATAL] Initial sync failed!")
        input("Press Enter to exit...")
        return False

    # Step 6: Final status
    pending, processed = check_audit_log_status()

    print("\n" + "="*70)
    print("INITIAL SYNC COMPLETED!")
    print("="*70)
    print(f"Records queued for CDC processing: {pending:,}")
    print("")
    print("NEXT STEPS:")
    print("1. Start CDC_Replicator.exe")
    print("2. CDC will process the queued records")
    print("3. Then continue with real-time sync")
    print("")
    print("The target database will be fully synchronized")
    print("after CDC_Replicator.exe processes all queued records.")

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Windows compatible auto-close
    print("\nPress any key to exit...")

    import msvcrt
    import time

    timeout = 10
    start_time = time.time()
    while time.time() - start_time < timeout:
        if msvcrt.kbhit():
            msvcrt.getch()
            break
        remaining = timeout - int(time.time() - start_time)
        if remaining > 0 and remaining != timeout:
            print(f"\rClosing in {remaining}s... (Press any key to exit)", end='', flush=True)
        time.sleep(0.1)

    print("\nExiting...")
    return True

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[STOP] Cancelled by user")
        input("Press Enter to exit...")
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}")
        input("Press Enter to exit...")




