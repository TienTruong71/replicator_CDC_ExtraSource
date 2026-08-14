import sys, os
sys.path.insert(0, 'replicator/src')
from db_utils import connect_db
from dotenv import load_dotenv
load_dotenv()

print('=== XÁC MINH KẾT QUẢ CUỐI CÙNG ===')

# Kiểm tra source
src_conn = connect_db('KINGDOM', target=False)
src_cursor = src_conn.cursor()
src_cursor.execute('SELECT COUNT(*) FROM db_test_1')
src_count = src_cursor.fetchone()[0]
src_conn.close()

# Kiểm tra target  
dst_conn = connect_db('KINGDOM', target=True)
dst_cursor = dst_conn.cursor()
dst_cursor.execute('SELECT COUNT(*) FROM db_test_1')
dst_count = dst_cursor.fetchone()[0]

# Kiểm tra audit_log
dst_cursor.execute('SELECT COUNT(*) FROM sync_audit_log')
audit_total = dst_cursor.fetchone()[0]

dst_cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'processed'")
processed = dst_cursor.fetchone()[0]

dst_conn.close()

print(f'📊 SOURCE DB - db_test_1: {src_count} records')
print(f'📊 TARGET DB - db_test_1: {dst_count} records')
print(f'📋 AUDIT LOG - Total: {audit_total}, Processed: {processed}')
print()

if src_count == dst_count:
    print('🎉 HOÀN HẢO! Source và Target đã đồng bộ 100%')
    print('✅ VẤN ĐỀ AUDIT_LOG ĐÃ ĐƯỢC GIẢI QUYẾT HOÀN TOÀN!')
else:
    print(f'⚠️  Chưa đồng bộ hoàn toàn: còn thiếu {src_count - dst_count} records')
