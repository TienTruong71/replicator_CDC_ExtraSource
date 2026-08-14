"""
Add unique constraint to sync_audit_log to prevent duplicate entries
"""

def add_unique_constraint_to_audit_log(conn):
    \"\"\"Add unique constraint to prevent duplicate audit log entries.\"\"\"
    cursor = conn.cursor()

    try:
        cursor.execute(\"\"\"
        SELECT COUNT(*) FROM sys.indexes
        WHERE name = 'IX_sync_audit_log_unique'
        AND object_id = OBJECT_ID('dbo.sync_audit_log')
        \"\"\")

        if cursor.fetchone()[0] > 0:
            print('[INFO] Unique constraint already exists on sync_audit_log')
            return True

        cursor.execute(\"\"\"
        CREATE UNIQUE INDEX IX_sync_audit_log_unique
        ON dbo.sync_audit_log (table_name, pk_value, status)
        WHERE status = 'pending'
        \"\"\")

        print('[SUCCESS] Added unique constraint to sync_audit_log')
        return True

    except Exception as e:
        print(f'[ERROR] Failed to add unique constraint: {e}')
        return False
    finally:
        cursor.close()

if __name__ == '__main__':
    from db_utils import connect_db

    conn = connect_db('KINGDOM', target=False)
    add_unique_constraint_to_audit_log(conn)
    conn.close()
