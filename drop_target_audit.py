import sys, os
sys.path.insert(0, 'replicator/src')
from db_utils import connect_db
from dotenv import load_dotenv
load_dotenv()

print('🗑️  XÓA sync_audit_log Ở TARGET DB')
print('=================================')

try:
    conn = connect_db('KINGDOM', target=True)
    cursor = conn.cursor()
    
    # Kiểm tra bảng tồn tại
    cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'sync_audit_log'")
    exists = cursor.fetchone()[0]
    
    if exists > 0:
        print('📋 Found sync_audit_log in TARGET DB')
        
        # Kiểm tra data
        cursor.execute('SELECT COUNT(*) FROM sync_audit_log')
        count = cursor.fetchone()[0]
        print(f'📊 Contains {count} records')
        
        # XÓA BẢNG
        cursor.execute('DROP TABLE sync_audit_log')
        conn.commit()
        
        print('🗑️  ✅ DELETED sync_audit_log from TARGET DB!')
        print('✅ TARGET DB now contains ONLY replicated data')
        
    else:
        print('ℹ️  sync_audit_log not found in TARGET DB (already clean)')
    
    conn.close()
    
    print()
    print('🏗️  ARCHITECTURE 1 COMPLETE:')
    print('   SOURCE DB: data + audit_log + triggers ✅')
    print('   TARGET DB: replicated data ONLY ✅')
    
except Exception as e:
    print(f'❌ Error: {e}')
