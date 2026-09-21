import os
import re
from dotenv import load_dotenv
import pyodbc
from datetime import datetime, date
import time
from decimal import Decimal

try:
    from logger import Logger
except ImportError:
    from .logger import Logger

load_dotenv()

FAST_EXEC_FAIL_CACHE = set()


def connect_db(prefix: str, target: bool = False):
    prefix = prefix.upper()
    if target:
        host = os.getenv(f"{prefix}_DST_SQLSERVER_HOST", os.getenv(f"{prefix}_SQLSERVER_HOST"))
        port = os.getenv(f"{prefix}_DST_SQLSERVER_PORT", "1433")
        user = os.getenv(f"{prefix}_DST_SQLSERVER_USER", os.getenv(f"{prefix}_SQLSERVER_USER"))
        password = os.getenv(f"{prefix}_DST_SQLSERVER_PASS", os.getenv(f"{prefix}_SQLSERVER_PASS"))
        database = os.getenv(f"{prefix}_DST_SQLSERVER_DB", os.getenv(f"{prefix}_SQLSERVER_DB"))
    else:
        host = os.getenv(f"{prefix}_SQLSERVER_HOST")
        port = os.getenv(f"{prefix}_SQLSERVER_PORT", "1433")
        user = os.getenv(f"{prefix}_SQLSERVER_USER")
        password = os.getenv(f"{prefix}_SQLSERVER_PASS")
        database = os.getenv(f"{prefix}_SQLSERVER_DB")

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={host},{port};DATABASE={database};UID={user};PWD={password};"
        f"TrustServerCertificate=yes;"
    )

    try:
        conn = pyodbc.connect(conn_str, autocommit=False)
        # Ensure ANSI SET options are correct for computed column indexes
        init_cursor = conn.cursor()
        init_cursor.execute(
            "SET ANSI_NULLS ON; "
            "SET ANSI_WARNINGS ON; "
            "SET ANSI_PADDING ON; "
            "SET CONCAT_NULL_YIELDS_NULL ON;"
        )
        init_cursor.close()
        conn.commit()
        Logger.info(f"Connected to {database} ({'target' if target else 'source'})")
        return conn
    except Exception as e:
        Logger.error(f"Cannot connect to SQL Server {database}", exc=e)
        raise


def ensure_table_exists(src_conn, dst_conn, table_name: str):
    table_name_clean = table_name.split(".")[-1]

    query_check = """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
    """
    dst_cursor = dst_conn.cursor()
    dst_cursor.execute(query_check, (table_name_clean,))
    exists = dst_cursor.fetchone()[0]
    if exists and exists > 0:
        return

    Logger.schema(f"Table dbo.[{table_name_clean}] not found on target. Initializing...")

    src_query = """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
        ORDER BY ORDINAL_POSITION
    """
    src_cursor = src_conn.cursor()
    src_cursor.execute(src_query, (table_name_clean,))
    rows = src_cursor.fetchall()
    if not rows:
        Logger.warn(f"Source table '{table_name}' not found — skipping create.")
        return

    col_defs = []
    for name, dtype, length, nullable in rows:
        dtype = (dtype or "").lower().strip()

        if dtype in ("varchar", "nvarchar", "char", "nchar", "text", "ntext"):
            if not length or length < 0 or length >= 50:
                col_defs.append(f"[{name}] NVARCHAR(MAX)")
            else:
                col_defs.append(f"[{name}] {dtype.upper()}({length})")
        else:
            col_defs.append(f"[{name}] {dtype.upper()}")

        if nullable == "YES":
            col_defs[-1] += " NULL"
        else:
            col_defs[-1] += " NOT NULL"

    ddl = f"CREATE TABLE dbo.[{table_name_clean}] (\n    {',\n    '.join(col_defs)}\n);"

    try:
        dst_cursor.execute(ddl)
        dst_conn.commit()
        Logger.success(f"Created dbo.[{table_name_clean}] on target server.")
    except Exception as e:
        dst_conn.rollback()
        Logger.error(f"Failed to create table {table_name_clean}", exc=e)


def get_primary_key(table_name: str, prefix: str, cursor=None):
    close_cursor = False
    if not cursor:
        conn = connect_db(prefix)
        cursor = conn.cursor()
        close_cursor = True

    table_name_clean = table_name.split(".")[-1]

    pk_query = f"""
        SELECT c.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c
            ON tc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
        WHERE tc.TABLE_NAME = '{table_name_clean}'
          AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
    """
    cursor.execute(pk_query)
    row = cursor.fetchone()
    if row:
        if close_cursor:
            cursor.connection.close()
        return row[0]

    try:
        cursor.execute(f"""
            SELECT TOP 1 col.name
            FROM sys.indexes ind
            INNER JOIN sys.index_columns ic ON ind.object_id = ic.object_id AND ind.index_id = ic.index_id
            INNER JOIN sys.columns col ON ic.object_id = col.object_id AND ic.column_id = col.column_id
            WHERE ind.is_unique = 1
              AND ind.object_id = OBJECT_ID('dbo.[{table_name_clean}]')
            ORDER BY ind.type_desc DESC
        """)
        row = cursor.fetchone()
        if row:
            if close_cursor:
                cursor.connection.close()
            return row[0]
    except Exception as e:
        Logger.warn(f"Warning searching unique index for {table_name_clean}: {e}")

    cursor.execute(
        f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_NAME='{table_name_clean}' AND LOWER(COLUMN_NAME) IN ('id', 'idx')"
    )
    row = cursor.fetchone()
    if row:
        if close_cursor:
            cursor.connection.close()
        return row[0]

    print(f"[{prefix}] {table_name_clean} has no unique key — falling back to first column.")
    col_query = f"""
        SELECT TOP 1 COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME='{table_name_clean}' ORDER BY ORDINAL_POSITION
    """
    cursor.execute(col_query)
    row = cursor.fetchone()
    if close_cursor:
        cursor.connection.close()
    return row[0] if row else None



##important
def upsert_data_odbc(dst_conn, table, rows, primary_key):
    """
    Safe UPSERT for SQL Server via ODBC.
    Auto-casts data to correct SQL types to prevent ODBC 07006 errors.
    """
    if not rows:
        return

    normalized_rows = []
    datetime_columns = get_datetime_columns(dst_conn, table)
    for r in rows:
        record = dict(r)
        for k, v in record.items():
            if isinstance(v, bytes):
                record[k] = v.decode("utf-8", errors="ignore").strip()
            elif isinstance(v, (datetime, date)):
                record[k] = v.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            elif isinstance(v, Decimal):
                record[k] = float(v)
            elif isinstance(v, str):
                if "T" in v and ":" in v:
                    record[k] = v.replace("T", " ").split(".")[0].replace("Z", "")
                if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}", v):
                    record[k] = v[:-3]
                else:
                    record[k] = v.strip()
                    if record[k] == "":
                        record[k] = None
            if k in datetime_columns:
                record[k] = convert_datetime(record[k])

            import uuid
            if isinstance(record[k], uuid.UUID):
                record[k] = str(record[k]).upper()

        normalized_rows.append(record)

    if not table.startswith("dbo."):
        table_full = f"dbo.[{table}]"
    else:
        if not table.startswith("dbo.["):
            name_part = table.replace("dbo.", "")
            table_full = f"dbo.[{name_part}]"
        else:
            table_full = table

    rows = [{k.lower(): v for k, v in r.items()} for r in normalized_rows]
    table_name_clean = table.replace("dbo.", "").replace("[", "").replace("]", "")

    try:
        cursor = dst_conn.cursor()
        cursor.fast_executemany = True

        # Step 1: detect identity columns
        cursor.execute(f"""
            SELECT c.name
            FROM sys.columns c
            JOIN sys.tables t ON c.object_id = t.object_id
            WHERE t.name = '{table_name_clean}' AND SCHEMA_NAME(t.schema_id) = 'dbo' AND c.is_identity = 1
        """)
        id_cols_res = cursor.fetchall()
        identity_cols = {r[0].lower() for r in id_cols_res} if id_cols_res else set()

        # Step 2: detect computed + timestamp columns and strip them from rows EARLY
        cursor.execute(f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table_name_clean}'
              AND (DATA_TYPE IN ('timestamp', 'rowversion')
                   OR COLUMNPROPERTY(OBJECT_ID(TABLE_SCHEMA + '.' + TABLE_NAME), COLUMN_NAME, 'IsComputed') = 1)
        """)
        excluded_cols = {r[0].lower() for r in cursor.fetchall()}
        if excluded_cols:
            Logger.info(f"Skipping auto-managed columns for {table}: {', '.join(excluded_cols)}")
            rows = [{k: v for k, v in row.items() if k not in excluded_cols} for row in rows]

        columns = list(rows[0].keys())

        if identity_cols:
            try:
                cursor.execute(f"SET IDENTITY_INSERT {table_full} ON")
            except Exception as e:
                Logger.warn(f"Failed to SET IDENTITY_INSERT ON for {table_full}: {e}")

        try:
            pk_col = (primary_key or columns[0]).lower()
            update_params = []
            insert_params = []


            cursor.execute(f"""
                SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = '{table_name_clean}'
                  AND DATA_TYPE IN ('varchar', 'nvarchar', 'char', 'nchar')
            """)
            char_limits = {r[0].lower(): r[1] for r in cursor.fetchall() if r[1] is not None and r[1] > 0}

            for row in rows:
                for c in columns:
                    cl = c.lower()
                    if cl in char_limits and isinstance(row.get(cl), str):
                        limit = char_limits[cl]
                        if len(row[cl]) > limit:
                            row[cl] = row[cl][:limit]

            col_list = ", ".join(f"[{c}]" for c in columns)
            placeholders_vals = ", ".join(["?" for _ in columns])
            update_cols = [c for c in columns if c.lower() != pk_col.lower() and c.lower() not in identity_cols]

            pks_in_batch = []
            for row in rows:
                pk_val = row.get(pk_col)
                if isinstance(pk_val, int):
                    pks_in_batch.append(str(pk_val))
                else:
                    pks_in_batch.append(str(pk_val))

            existing_pks = set()
            chunk_size_check = 1000
            for i in range(0, len(pks_in_batch), chunk_size_check):
                chunk = pks_in_batch[i : i + chunk_size_check]
                placeholders_pk = ", ".join(["?" for _ in chunk])
                check_query = f"SELECT [{pk_col}] FROM {table_full} WHERE [{pk_col}] IN ({placeholders_pk})"
                cursor.execute(check_query, tuple(chunk))
                existing_pks.update({str(r[0]) for r in cursor.fetchall()})

            for row in rows:
                pk_val = row.get(pk_col)
                str_pk = str(pk_val)

                if str_pk in existing_pks:
                    update_values = [row.get(c) for c in update_cols]
                    update_params.append(tuple(update_values + [pk_val]))
                else:
                    insert_values = [row.get(c) for c in columns]
                    insert_params.append(tuple(insert_values))

            num_columns = len(columns)
            dml_chunk_size = max(10, 2000 // (num_columns + 1))
            dml_chunk_size = min(dml_chunk_size, 500)

            if update_params and update_cols:
                set_clauses_exec = ", ".join([f"[{c}] = ?" for c in update_cols])
                update_sql = f"UPDATE {table_full} SET {set_clauses_exec} WHERE [{pk_col}] = ?"
                chunk_size_exec = 1000
                use_fast_update = table_full not in FAST_EXEC_FAIL_CACHE

                for i in range(0, len(update_params), chunk_size_exec):
                    chunk = update_params[i:i+chunk_size_exec]
                    success = False
                    if use_fast_update:
                        try:
                            cursor.executemany(update_sql, chunk)
                            success = True
                        except Exception:
                            FAST_EXEC_FAIL_CACHE.add(table_full)
                            use_fast_update = False
                            Logger.warn(f"Switching {table} UPDATE to stable sync mode.")

                    if not success:
                        for row_params in chunk:
                            try:
                                cursor.execute(update_sql, row_params)
                            except Exception as row_error:
                                Logger.error(f"Row-level update failed in {table}", exc=row_error)

            if insert_params:
                insert_sql = f"INSERT INTO {table_full} ({col_list}) VALUES ({placeholders_vals})"
                chunk_size_exec = 1000
                use_fast = table_full not in FAST_EXEC_FAIL_CACHE

                for i in range(0, len(insert_params), chunk_size_exec):
                    chunk = insert_params[i:i+chunk_size_exec]
                    success = False
                    if use_fast:
                        try:
                            cursor.executemany(insert_sql, chunk)
                            success = True
                        except Exception:
                            FAST_EXEC_FAIL_CACHE.add(table_full)
                            use_fast = False
                            Logger.warn(f"Switching {table} to stable sync mode (fast mode unsupported).")

                    if not success:
                        sub_chunk_size = 200
                        for j in range(0, len(chunk), sub_chunk_size):
                            sub_chunk = chunk[j:j+sub_chunk_size]
                            v_placeholders = ", ".join(["(" + ", ".join(["?"] * len(columns)) + ")"] * len(sub_chunk))
                            # sub_chunk contains tuples - flatten correctly
                            f_params = [val for row_tuple in sub_chunk for val in row_tuple]
                            try:
                                cursor.execute(f"INSERT INTO {table_full} ({col_list}) VALUES {v_placeholders}", f_params)
                            except Exception as sub_error:
                                Logger.error(f"Batch insert failed in {table}, trying final row-by-row fallback...", exc=sub_error)
                                # Create a fresh cursor to avoid corrupted state from batch failure
                                fallback_cursor = dst_conn.cursor()
                                if identity_cols:
                                    try:
                                        fallback_cursor.execute(f"SET IDENTITY_INSERT {table_full} ON")
                                    except Exception:
                                        pass
                                for row_params in sub_chunk:
                                    try:
                                        fallback_cursor.execute(insert_sql, row_params)
                                    except Exception as row_error:
                                        for col_name, val in zip(columns, row_params):
                                            if isinstance(val, str) and len(val) > 100:
                                                Logger.error(f"  Suspect col [{col_name}] len={len(val)}: {val[:80]}...")
                                        Logger.error(f"Row-level insert failed in {table}", exc=row_error)
                                if identity_cols:
                                    try:
                                        fallback_cursor.execute(f"SET IDENTITY_INSERT {table_full} OFF")
                                    except Exception:
                                        pass
                                fallback_cursor.close()

            dst_conn.commit()
            Logger.success(f"Upserted {len(rows)} rows into {table_full} (U:{len(update_params)} I:{len(insert_params)})")

        finally:
            if identity_cols:
                try:
                    cursor.execute(f"SET IDENTITY_INSERT {table_full} OFF")
                except Exception:
                    pass

    except Exception as e:
        try:
            dst_conn.rollback()
        except Exception:
            pass
        Logger.error(f"Upsert failed for {table} — skipping this batch to avoid crash", exc=e)


def delete_data_odbc(conn, table, before, primary_key="id"):
    if not before:
        return

    pk_value = before.get(primary_key)
    if pk_value is None:
        print(f"Delete skipped: no primary key value in {before}")
        return

    cursor = conn.cursor()
    if not table.startswith("dbo."):
        table_full = f"dbo.[{table}]"
    elif not table.startswith("dbo.["):
        name_part = table.replace("dbo.", "")
        table_full = f"dbo.[{name_part}]"
    else:
        table_full = table

    try:
        cursor.execute(f"DELETE FROM {table_full} WHERE [{primary_key}] = ?", (pk_value,))
        conn.commit()
        print(f"Deleted record from {table_full} WHERE {primary_key}={pk_value}")
    except Exception as e:
        conn.rollback()
        print(f"Delete failed for {table}: {e}")


def sync_schema_direct(src_conn, dst_conn, schema, table):
    src_cursor = src_conn.cursor()
    dst_cursor = dst_conn.cursor()

    src_cursor.execute(
        f"SELECT COLUMN_NAME, DATA_TYPE, COALESCE(CHARACTER_MAXIMUM_LENGTH, 0) "
        f"FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'"
    )
    src_cols = {row[0]: {"type": row[1].lower(), "length": int(row[2])} for row in src_cursor.fetchall()}

    dst_cursor.execute(
        f"SELECT COLUMN_NAME, DATA_TYPE, COALESCE(CHARACTER_MAXIMUM_LENGTH, 0) "
        f"FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'"
    )
    dst_cols = {row[0]: {"type": row[1].lower(), "length": int(row[2])} for row in dst_cursor.fetchall()}

    sql_updates = []
    for col, meta in src_cols.items():
        if col not in dst_cols:
            sql_updates.append(f"ALTER TABLE [{schema}].[{table}] ADD [{col}] {to_sql_type(meta)}")

    if not sql_updates:
        return

    now = time.strftime('%H:%M:%S')
    print(f"[{now}] [SCHEMA] Detected {len(sql_updates)} new column(s) for table: {table}")
    for sql in sql_updates:
        try:
            dst_cursor.execute(sql)
            print(f"  > Executed: {sql}")
        except Exception as e:
            print(f"  > [ERROR] Failed to sync column: {e}")

    dst_conn.commit()
    Logger.success(f"Schema synchronized successfully for {table}")


def fetch_rows_by_pks(src_conn, schema, table, pk_col, pks):
    if not pks:
        return []

    results = []
    chunk_size = 2000
    for i in range(0, len(pks), chunk_size):
        chunk = pks[i : i + chunk_size]
        placeholders = ", ".join(["?" for _ in chunk])
        query = f"SELECT * FROM [{schema}].[{table}] WHERE [{pk_col}] IN ({placeholders})"

        cursor = src_conn.cursor()
        try:
            cursor.execute(query, tuple(chunk))
            desc = cursor.description
            if desc:
                columns = [column[0] for column in desc]
                results.extend([dict(zip(columns, row)) for row in cursor.fetchall()])
            cursor.close()
        except Exception as e:
            if '42S02' in str(e) or 'Invalid object name' in str(e):
                Logger.warn(f"Source table {schema}.{table} not found. Skipping chunk.")
            else:
                Logger.error(f"Error fetching chunk for {schema}.{table}", exc=e)
            try: cursor.close()
            except: pass

    return results


def to_sql_type(meta):
    """Convert a column metadata dict to a SQL Server type string.
    meta = { "type": "varchar", "length": 255 }
    """
    t = meta["type"].lower()
    length = meta.get("length", 0)

    if t in ("varchar", "char", "string", "text"):
        if length <= 0 or length > 4000:
            return "VARCHAR(MAX)"
        return f"VARCHAR({length})"

    if t in ("nvarchar", "nchar", "nstring"):
        if length <= 0 or length > 4000:
            return "NVARCHAR(MAX)"
        return f"NVARCHAR({length})"

    if t in ("int", "integer"):
        return "INT"
    if t == "bigint":
        return "BIGINT"
    if t == "smallint":
        return "SMALLINT"
    if t == "tinyint":
        return "TINYINT"

    if t in ("decimal", "numeric"):
        return f"DECIMAL(18,4)"

    if t in ("float", "double", "real"):
        return "FLOAT"

    if t in ("datetime", "timestamp", "datetime2"):
        return "DATETIME2"

    if t == "date":
        return "DATE"

    if t in ("bool", "boolean"):
        return "BIT"

    if t in ("binary", "varbinary", "bytes"):
        if length <= 0 or length > 8000:
            return "VARBINARY(MAX)"
        return f"VARBINARY({length})"

    if t == "uniqueidentifier":
        return "UNIQUEIDENTIFIER"

    return "NVARCHAR(MAX)"


def convert_datetime(ms):
    if ms is None:
        return None
    if isinstance(ms, (int, float)) and ms > 100000000000:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return ms


def get_datetime_columns(conn, table):
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '{table}'
          AND DATA_TYPE IN ('datetime', 'datetime2', 'smalldatetime', 'date', 'time', 'datetimeoffset')
    """)
    return {row[0] for row in cursor.fetchall()}
