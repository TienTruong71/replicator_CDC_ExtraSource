"""
Schema Validation for Multi-Source Sync
Validates table schemas across multiple sources to prevent conflicts
"""

import time
from typing import Dict, List, Tuple, Optional

try:
    from logger import Logger
except ImportError:
    from .logger import Logger


class SchemaConflict:
    """Represents a schema conflict between sources."""
    
    def __init__(self, table_name: str, conflict_type: str, details: str, 
                 source1: str, source2: str):
        self.table_name = table_name
        self.conflict_type = conflict_type  # 'column_type', 'primary_key', 'missing_column'
        self.details = details
        self.source1 = source1
        self.source2 = source2
        self.severity = self._calculate_severity()
    
    def _calculate_severity(self) -> str:
        if self.conflict_type in ['primary_key', 'column_type']:
            return 'CRITICAL'
        elif self.conflict_type == 'missing_column':
            return 'WARNING'
        return 'INFO'
    
    def __str__(self) -> str:
        return f"[{self.severity}] {self.table_name}: {self.details} ({self.source1} vs {self.source2})"


class SchemaValidator:
    """Multi-source schema validation engine."""
    
    def __init__(self):
        self.conflicts = []
        self.validated_tables = set()
    
    def get_table_schema(self, conn, schema: str, table: str) -> Dict[str, Dict]:
        """Get complete schema information for a table."""
        cursor = conn.cursor()
        
        # Get column information
        cursor.execute(f"""
            SELECT 
                COLUMN_NAME, 
                DATA_TYPE, 
                COALESCE(CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, 0) as LENGTH,
                IS_NULLABLE,
                COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'
            ORDER BY ORDINAL_POSITION
        """)
        
        columns = {}
        for row in cursor.fetchall():
            col_name, data_type, length, nullable, default = row
            columns[col_name] = {
                'type': data_type.lower(),
                'length': int(length) if length else 0,
                'nullable': nullable == 'YES',
                'default': default
            }
        
        # Get primary key information
        cursor.execute(f"""
            SELECT c.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c 
                ON tc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
            WHERE tc.TABLE_SCHEMA = '{schema}' 
                AND tc.TABLE_NAME = '{table}'
                AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ORDER BY c.ORDINAL_POSITION
        """)
        
        primary_keys = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        
        return {
            'columns': columns,
            'primary_keys': primary_keys,
            'table_name': table
        }
    
    def validate_multi_source_table(self, table_name: str, 
                                  source_schemas: List[Tuple[str, any, str]]) -> List[SchemaConflict]:
        """
        Validate a table across multiple sources.
        
        Args:
            table_name: Name of the table to validate
            source_schemas: List of (source_id, connection, schema) tuples
            
        Returns:
            List of schema conflicts found
        """
        if len(source_schemas) < 2:
            return []  # No conflicts possible with single source
        
        Logger.info(f"🔍 Validating schema for table '{table_name}' across {len(source_schemas)} sources...")
        
        # Get schemas from all sources
        schemas = {}
        for source_id, conn, schema in source_schemas:
            try:
                table_schema = self.get_table_schema(conn, schema, table_name)
                if table_schema['columns']:  # Table exists in this source
                    schemas[source_id] = table_schema
            except Exception as e:
                Logger.warn(f"Could not get schema for {table_name} from {source_id}: {e}")
        
        if len(schemas) < 2:
            return []  # Need at least 2 schemas to compare
        
        # Compare schemas pairwise
        conflicts = []
        source_ids = list(schemas.keys())
        
        for i in range(len(source_ids)):
            for j in range(i + 1, len(source_ids)):
                source1_id = source_ids[i]
                source2_id = source_ids[j]
                source1_schema = schemas[source1_id]
                source2_schema = schemas[source2_id]
                
                # Validate primary keys
                if source1_schema['primary_keys'] != source2_schema['primary_keys']:
                    conflict = SchemaConflict(
                        table_name=table_name,
                        conflict_type='primary_key',
                        details=f"Primary key mismatch: {source1_schema['primary_keys']} vs {source2_schema['primary_keys']}",
                        source1=source1_id,
                        source2=source2_id
                    )
                    conflicts.append(conflict)
                
                # Validate column compatibility
                all_columns = set(source1_schema['columns'].keys()) | set(source2_schema['columns'].keys())
                
                for col_name in all_columns:
                    col1 = source1_schema['columns'].get(col_name)
                    col2 = source2_schema['columns'].get(col_name)
                    
                    if col1 and col2:
                        # Both sources have the column - check compatibility
                        if col1['type'] != col2['type']:
                            conflict = SchemaConflict(
                                table_name=table_name,
                                conflict_type='column_type',
                                details=f"Column '{col_name}' type mismatch: {col1['type']} vs {col2['type']}",
                                source1=source1_id,
                                source2=source2_id
                            )
                            conflicts.append(conflict)
                        
                        elif col1['length'] != col2['length'] and col1['length'] > 0 and col2['length'] > 0:
                            conflict = SchemaConflict(
                                table_name=table_name,
                                conflict_type='column_length',
                                details=f"Column '{col_name}' length mismatch: {col1['length']} vs {col2['length']}",
                                source1=source1_id,
                                source2=source2_id
                            )
                            conflicts.append(conflict)
                    
                    elif col1 and not col2:
                        # Column only in source1
                        conflict = SchemaConflict(
                            table_name=table_name,
                            conflict_type='missing_column',
                            details=f"Column '{col_name}' exists in {source1_id} but not in {source2_id}",
                            source1=source1_id,
                            source2=source2_id
                        )
                        conflicts.append(conflict)
                    
                    elif col2 and not col1:
                        # Column only in source2
                        conflict = SchemaConflict(
                            table_name=table_name,
                            conflict_type='missing_column',
                            details=f"Column '{col_name}' exists in {source2_id} but not in {source1_id}",
                            source1=source2_id,
                            source2=source1_id
                        )
                        conflicts.append(conflict)
        
        # Log results
        if conflicts:
            Logger.warn(f"Found {len(conflicts)} schema conflicts for table '{table_name}':")
            for conflict in conflicts:
                if conflict.severity == 'CRITICAL':
                    Logger.error(f"  {conflict}")
                else:
                    Logger.warn(f"  {conflict}")
        else:
            Logger.success(f"Schema validation passed for table '{table_name}'")
        
        self.conflicts.extend(conflicts)
        self.validated_tables.add(table_name)
        
        return conflicts
    
    def has_critical_conflicts(self) -> bool:
        """Check if there are any critical schema conflicts."""
        return any(conflict.severity == 'CRITICAL' for conflict in self.conflicts)
    
    def get_critical_conflicts(self) -> List[SchemaConflict]:
        """Get list of critical conflicts that must be resolved."""
        return [c for c in self.conflicts if c.severity == 'CRITICAL']
    
    def print_summary(self):
        """Print validation summary."""
        if not self.conflicts:
            Logger.success(f"✅ Schema validation passed for {len(self.validated_tables)} tables")
            return
        
        critical = len([c for c in self.conflicts if c.severity == 'CRITICAL'])
        warnings = len([c for c in self.conflicts if c.severity == 'WARNING'])
        
        print(f"\n📋 SCHEMA VALIDATION SUMMARY:")
        print(f"  Tables validated: {len(self.validated_tables)}")
        print(f"  Critical conflicts: {critical}")
        print(f"  Warnings: {warnings}")
        
        if critical > 0:
            print(f"\n🚨 CRITICAL CONFLICTS (must be resolved):")
            for conflict in self.get_critical_conflicts():
                print(f"  {conflict}")
