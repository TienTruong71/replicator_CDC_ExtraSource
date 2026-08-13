import os
import sys

_src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replicator", "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from dotenv import load_dotenv
load_dotenv()

try:
    from db_utils import connect_db
except ImportError as e:
    print(f"Could not import db_utils: {e}")
    sys.exit(1)

def check_schema_diff():
    print("=== Full schema comparison: source vs target ===\n")
    prefix = "KINGDOM"

    src_conn = connect_db(prefix, target=False)
    dst_conn = connect_db(prefix, target=True)

    tables = ['dimension_data', 'dimension_detail_data', 'dimension_detail_data_new']

    src_cursor = src_conn.cursor()
    dst_cursor = dst_conn.cursor()

    for table in tables:
        print(f"\n{'='*60}")
        print(f"TABLE: {table}")
        print(f"{'='*60}")

        src_cursor.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE,
                   COALESCE(CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, DATETIME_PRECISION, 0) as size,
                   IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table}' AND TABLE_SCHEMA = 'dbo'
            ORDER BY ORDINAL_POSITION
        """)
        src_cols = {r[0].lower(): {"type": r[1], "size": r[2], "nullable": r[3]} for r in src_cursor.fetchall()}

        dst_cursor.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE,
                   COALESCE(CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, DATETIME_PRECISION, 0) as size,
                   IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table}' AND TABLE_SCHEMA = 'dbo'
            ORDER BY ORDINAL_POSITION
        """)
        dst_cols = {r[0].lower(): {"type": r[1], "size": r[2], "nullable": r[3]} for r in dst_cursor.fetchall()}

        print(f"{'Column':<30} {'Src Type':<20} {'Dst Type':<20} {'Status'}")
        print(f"{'-'*90}")

        all_cols = sorted(set(list(src_cols.keys()) + list(dst_cols.keys())))
        for col in all_cols:
            src = src_cols.get(col)
            dst = dst_cols.get(col)

            if not src:
                print(f"  {col:<28} {'(missing)':<20} {dst['type']:<20} [DST ONLY]")
            elif not dst:
                print(f"  {col:<28} {src['type']:<20} {'(missing)':<20} [SRC ONLY - will be auto-created]")
            else:
                src_t = f"{src['type']}({src['size']})" if src['size'] else src['type']
                dst_t = f"{dst['type']}({dst['size']})" if dst['size'] else dst['type']
                status = "[OK]" if src['type'].lower() == dst['type'].lower() else "[TYPE MISMATCH]"
                print(f"  {col:<28} {src_t:<20} {dst_t:<20} {status}")

    src_conn.close()
    dst_conn.close()
    print("\nDone.")

if __name__ == "__main__":
    check_schema_diff()
