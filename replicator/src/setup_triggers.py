import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

try:
    from db_utils import connect_db, ensure_table_exists
    from logger import Logger
except ImportError:
    from .db_utils import connect_db, ensure_table_exists
    from .logger import Logger

load_dotenv()


def _get_pk_for_table(cursor, table: str):
    """
    Return PK column name for a table with priority:
    1. Official Primary Key
    2. Unique Index
    3. Column named 'id' or 'ID'
    4. First available column
    """
    cursor.execute(f"""
        SELECT c.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c ON tc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
        WHERE tc.TABLE_NAME = '{table}' AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
    """)
    row = cursor.fetchone()
    if row:
        return row[0]

    try:
        cursor.execute(f"""
            SELECT TOP 1 col.name
            FROM sys.indexes ind
            INNER JOIN sys.index_columns ic ON ind.object_id = ic.object_id AND ind.index_id = ic.index_id
            INNER JOIN sys.columns col ON ic.object_id = col.object_id AND ic.column_id = col.column_id
            WHERE ind.is_unique = 1
              AND ind.object_id = OBJECT_ID('dbo.[{table}]')
            ORDER BY ind.type_desc DESC
        """)
        row = cursor.fetchone()
        if row:
            return row[0]
    except Exception as e:
        Logger.warn(f"Warning searching unique index for {table}: {e}")

    cursor.execute(
        f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_NAME='{table}' AND (COLUMN_NAME = 'id' OR COLUMN_NAME = 'ID')"
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        f"SELECT TOP 1 COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_NAME='{table}' ORDER BY ORDINAL_POSITION"
    )
    row = cursor.fetchone()
    if row:
        Logger.warn(f"Table {table} has no unique key! Falling back to first column [{row[0]}]. Risk of duplicates!")
        return row[0]

    return None


def setup_single_table(conn, table: str, insert_only: bool = False) -> bool:
    """
    Setup CDC triggers and queue existing rows for a single table.
    Returns True if successful, False otherwise.
    """
    cursor = conn.cursor()
    try:
        clean_table = table.replace(' ', '_')
        pk_col = _get_pk_for_table(cursor, table)
        if not pk_col:
            Logger.warn(f"Table {table} has no columns. Skipping.")
            return False

        Logger.info(f"Using '{pk_col}' as sync key for {table}.", indent=1)

        for op in ['INS', 'UPD', 'DEL']:
            try:
                cursor.execute(
                    f"IF OBJECT_ID('dbo.[trig_cdc_{clean_table}_{op}]', 'TR') IS NOT NULL "
                    f"DROP TRIGGER dbo.[trig_cdc_{clean_table}_{op}]"
                )
            except Exception as e:
                Logger.warn(f"Warning dropping old trigger for {table}: {e}", indent=1)


        cursor.execute(f"""
        CREATE TRIGGER dbo.[trig_cdc_{clean_table}_INS] ON dbo.[{table}] AFTER INSERT AS
        BEGIN
            SET NOCOUNT ON;
            INSERT INTO dbo.sync_audit_log (table_name, pk_value, operation, status)
            SELECT '{table}', CAST([{pk_col}] AS NVARCHAR(MAX)), 'I', 'pending' FROM inserted;
        END
        """)

        if not insert_only:
            cursor.execute(f"""
            CREATE TRIGGER dbo.[trig_cdc_{clean_table}_UPD] ON dbo.[{table}] AFTER UPDATE AS
            BEGIN
                SET NOCOUNT ON;
                INSERT INTO dbo.sync_audit_log (table_name, pk_value, operation, status)
                SELECT '{table}', CAST([{pk_col}] AS NVARCHAR(MAX)), 'U', 'pending' FROM inserted;
            END
            """)

        conn.commit()
        Logger.info(f"Triggers for {table} successfully created.", indent=1)
        return True

    except Exception as e:
        conn.rollback()
        err_msg = str(e)
        if "insufficient disk space" in err_msg.lower() or "1101" in err_msg:
            Logger.error(f"CRITICAL: Disk Space Full on Source Database! Cannot setup triggers for {table}.")
        else:
            Logger.error(f"Failed to setup triggers for {table}", exc=e)
        return False
    finally:
        cursor.close()


def ensure_audit_log_table(conn):
    """Ensures that the dbo.sync_audit_log table and its indexes exist with multi-source support."""
    cursor = conn.cursor()
    Logger.info("Ensuring dbo.sync_audit_log exists with multi-source columns...")

    
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sync_audit_log' AND schema_id = SCHEMA_ID('dbo'))
    CREATE TABLE dbo.sync_audit_log (
        log_id    BIGINT IDENTITY(1,1) PRIMARY KEY,
        table_name NVARCHAR(255),
        pk_value  NVARCHAR(255),
        operation CHAR(1),
        created_at DATETIME DEFAULT GETDATE()
    );
    """)

    
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.sync_audit_log') AND name = 'status')
    BEGIN
        ALTER TABLE dbo.sync_audit_log ADD status VARCHAR(20) NOT NULL DEFAULT 'pending'
        PRINT 'Added status column to sync_audit_log table'
    END
    """)

    
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.sync_audit_log') AND name = 'processed_at')
    BEGIN
        ALTER TABLE dbo.sync_audit_log ADD processed_at DATETIME NULL
        PRINT 'Added processed_at column to sync_audit_log table'
    END
    """)

    
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('dbo.sync_audit_log') AND name = 'source_id')
    BEGIN
        ALTER TABLE dbo.sync_audit_log ADD source_id VARCHAR(50) NULL
        PRINT 'Added source_id column to sync_audit_log table'
    END
    """)


    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_sync_audit_log_table' AND object_id = OBJECT_ID('dbo.sync_audit_log'))
    CREATE INDEX IX_sync_audit_log_table ON dbo.sync_audit_log (table_name);
    """)

    
    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_sync_audit_log_status' AND object_id = OBJECT_ID('dbo.sync_audit_log'))
    CREATE INDEX IX_sync_audit_log_status ON dbo.sync_audit_log (status, log_id);
    """)


    cursor.execute("""
    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_sync_audit_log_source' AND object_id = OBJECT_ID('dbo.sync_audit_log'))
    CREATE INDEX IX_sync_audit_log_source ON dbo.sync_audit_log (source_id, created_at) WHERE source_id IS NOT NULL;
    """)

    conn.commit()
    cursor.close()


def setup_triggers():
    try:
        from multi_source_config import MultiSourceConfig
    except ImportError:
        from .multi_source_config import MultiSourceConfig

    config_mgr = MultiSourceConfig()
    sources = config_mgr.get_all_sources()
    
    if not sources:
        Logger.error("No sources configured for CDC Trigger Setup.")
        return

    for source_id, config in sources.items():
        prefix = config.prefix
        print(f"Starting CDC Trigger Setup for Source: {source_id} ({config.database})")

        try:
            conn = connect_db(prefix, target=False)
            ensure_audit_log_table(conn)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                  AND TABLE_SCHEMA = 'dbo'
                  AND TABLE_NAME NOT IN ('sync_audit_log', 'sysdiagrams', 'sync_dedup_tracker')
                  AND TABLE_NAME NOT LIKE 'sys%'
                  AND TABLE_NAME NOT LIKE 'MSr%'
                  AND TABLE_NAME NOT LIKE '%[_]tracking'
            """)
            tables = [row[0] for row in cursor.fetchall()]
            cursor.close()

            sync_tables = os.getenv(f"{prefix}_SYNC_TABLES")
            if sync_tables:
                allowed_tables = [t.strip() for t in sync_tables.split(",")]
                print(f"Limiting sync to specific tables: {', '.join(allowed_tables)}")
                tables = [t for t in tables if t in allowed_tables]

            for table in tables:
                print(f"Setting up CDC for: {table} (Insert Only: {config.insert_only})")
                setup_single_table(conn, table, insert_only=config.insert_only)

            conn.commit()
            Logger.success(f"CDC Trigger Setup Process Complete for {source_id}.")
            conn.close()
        except Exception as e:
            Logger.error(f"Failed to setup triggers for {source_id}", exc=e)

def auto_discover_new_tables(conn, prefix: str, insert_only: bool = False):
    ensure_audit_log_table(conn)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME NOT IN ('sync_audit_log', 'sysdiagrams', 'sync_dedup_tracker')
          AND TABLE_NAME NOT LIKE 'sys%'
          AND TABLE_NAME NOT LIKE 'MSr%'
          AND TABLE_NAME NOT LIKE '%[_]tracking'
    """)
    all_tables = [r[0] for r in cursor.fetchall()]

    sync_tables = os.getenv(f"{prefix}_SYNC_TABLES")
    if sync_tables:
        allowed_tables = [t.strip() for t in sync_tables.split(",")]
        all_tables = [t for t in all_tables if t in allowed_tables]

    
    expected_count = 1 if insert_only else 2
    
    cursor.execute(f"""
        SELECT OBJECT_NAME(parent_id)
        FROM sys.triggers
        WHERE name LIKE 'trig_cdc_%' AND parent_class_desc = 'OBJECT_OR_COLUMN'
        GROUP BY parent_id
        HAVING COUNT(*) >= {expected_count}
    """)
    triggered_tables = {r[0] for r in cursor.fetchall() if r[0]}

    new_tables = []
    for table in all_tables:
        if table not in triggered_tables:
            Logger.info(f"[Auto-Discovery] Detected missing or partial triggers for: {table}")
            if setup_single_table(conn, table, insert_only=insert_only):
                new_tables.append(table)

    cursor.close()
    return new_tables

def get_monitored_tables(conn, prefix: str, insert_only: bool = False):
    """Returns a list of tables that currently have CDC triggers and are allowed by config."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME NOT IN ('sync_audit_log', 'sysdiagrams', 'sync_dedup_tracker')
          AND TABLE_NAME NOT LIKE 'sys%'
          AND TABLE_NAME NOT LIKE 'MSr%'
          AND TABLE_NAME NOT LIKE '%[_]tracking'
    """)
    all_tables = [r[0] for r in cursor.fetchall()]

    sync_tables = os.getenv(f"{prefix}_SYNC_TABLES")
    if sync_tables:
        allowed = [t.strip() for t in sync_tables.split(",")]
        all_tables = [t for t in all_tables if t in allowed]

    expected_count = 1 if insert_only else 2

    cursor.execute(f"""
        SELECT OBJECT_NAME(parent_id)
        FROM sys.triggers
        WHERE name LIKE 'trig_cdc_%' AND parent_class_desc = 'OBJECT_OR_COLUMN'
        GROUP BY parent_id
        HAVING COUNT(*) >= {expected_count}
    """)
    triggered_tables = {r[0] for r in cursor.fetchall() if r[0]}

    cursor.close()
    return [t for t in all_tables if t in triggered_tables]

if __name__ == "__main__":
    setup_triggers()