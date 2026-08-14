"""
Test Schema Validation với Multi-Source
"""

import sys, os
sys.path.insert(0, 'replicator/src')
from schema_validator import SchemaValidator
from db_utils import connect_db
from dotenv import load_dotenv

load_dotenv()

def test_schema_validation():
    print('🔍 TESTING MULTI-SOURCE SCHEMA VALIDATION')
    print('=========================================')
    
    validator = SchemaValidator()
    
    # Giả lập test với 2 sources cùng table name
    print('\n📋 Test case: Cùng table name "db_test_1" từ multiple sources')
    
    # Trong thực tế, sẽ có nhiều sources với cùng table name
    sources = [
        ('KINGDOM_SOURCE1', connect_db('KINGDOM', target=False), 'dbo'),
        # ('KINGDOM_SOURCE2', connect_db('KINGDOM2', target=False), 'dbo'),  # Uncomment khi có source 2
    ]
    
    # Test validation
    conflicts = validator.validate_multi_source_table('db_test_1', sources)
    
    # Print summary
    validator.print_summary()
    
    if validator.has_critical_conflicts():
        print('\n🚨 CRITICAL: Schema conflicts found! Review before syncing.')
        return False
    else:
        print('\n✅ Schema validation passed - safe to sync')
        return True

if __name__ == '__main__':
    test_schema_validation()
