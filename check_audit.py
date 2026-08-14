import sys, os
sys.path.insert(0, 'replicator/src')
from db_utils import connect_db
from dotenv import load_dotenv
load_dotenv()

print('=== AUDIT_LOG STATUS ===')

conn = connect_db('KINGDOM', target=True)
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM sync_audit_log WHERE status = ''pending''')
pending = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM sync_audit_log WHERE status = ''processed''')
processed = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM sync_audit_log')
total = cursor.fetchone()[0]

print(f'📋 Total audit records: {total}')
print(f'⏳ Pending: {pending}')
print(f'✅ Processed: {processed}')

if pending > 0:
    print(f'\\n🎯 Có {pending} records cần CDC_Replicator xử lý!')
    
    # Sample pending records
    cursor.execute('SELECT TOP 3 table_name, pk_value, operation FROM sync_audit_log WHERE status = ''pending''')
    print('\\nSample pending records:')
    for row in cursor.fetchall():
        print(f'  {row[0]} | PK:{row[1]} | Op:{row[2]}')
else:
    print('\\n✅ Không có pending records!')

conn.close()
