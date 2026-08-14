"""
Simple Column Validator - Only check column names and count
Validates SOURCE vs TARGET table compatibility for CDC sync
"""

class SimpleColumnValidator:
    def __init__(self):
        self.issues = []
        
    def validate_table(self, src_conn, dst_conn, table_name):
        """
        Validate table compatibility - Only check column names and count
        Returns True if compatible, False if critical issues found
        """
        try:
            print(f"[INFO] Validating table: {table_name} (columns only)")
            
            # Get source columns
            src_columns = self._get_column_names(src_conn, table_name)
            if not src_columns:
                self.issues.append(f"{table_name}: Source table not found or has no columns")
                return False
                
            # Get target columns  
            dst_columns = self._get_column_names(dst_conn, table_name)
            if not dst_columns:
                self.issues.append(f"{table_name}: Target table not found or has no columns")
                return False
                
            # Check column count
            if len(src_columns) != len(dst_columns):
                self.issues.append(f"{table_name}: Column count mismatch - Source: {len(src_columns)}, Target: {len(dst_columns)}")
                print(f"[ERROR] {table_name}: Column count mismatch")
                print(f"[ERROR]    SOURCE: {len(src_columns)} columns")  
                print(f"[ERROR]    TARGET: {len(dst_columns)} columns")
                return False
                
            # Check column names match
            src_set = set(src_columns)
            dst_set = set(dst_columns)
            
            missing_in_target = src_set - dst_set
            extra_in_target = dst_set - src_set
            
            if missing_in_target:
                self.issues.append(f"{table_name}: Missing columns in target: {list(missing_in_target)}")
                print(f"[ERROR] {table_name}: Missing columns in TARGET: {list(missing_in_target)}")
                return False
                
            if extra_in_target:
                self.issues.append(f"{table_name}: Extra columns in target: {list(extra_in_target)}")
                print(f"[ERROR] {table_name}: Extra columns in TARGET: {list(extra_in_target)}")
                return False
                
            print(f"[OK] {table_name}: Column structure compatible ({len(src_columns)} columns)")
            return True
            
        except Exception as e:
            error_msg = f"{table_name}: Validation error - {str(e)}"
            self.issues.append(error_msg)
            print(f"[ERROR] {error_msg}")
            return False
            
    def _get_column_names(self, conn, table_name):
        """Get list of column names from table"""
        try:
            cursor = conn.cursor()
            
            # Get column names only
            cursor.execute(f"""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = '{table_name}'
                ORDER BY ORDINAL_POSITION
            """)
            
            columns = [row[0].lower() for row in cursor.fetchall()]
            return columns
            
        except Exception as e:
            print(f"[ERROR] Failed to get columns for {table_name}: {e}")
            return []

