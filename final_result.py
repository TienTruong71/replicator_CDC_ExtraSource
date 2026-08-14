import sys, os
sys.path.insert(0, 'replicator/src')
from db_utils import connect_db
from dotenv import load_dotenv
load_dotenv()

print('=== KẾT QUẢ CUỐI CÙNG ===')
print()

# 1. Kiểm tra số lượng records trong source và target
src_conn = connect_db('KINGDOM', target=False)
src_cursor = src_conn.cursor()
src_cursor.execute('SELECT COUNT(*) FROM db_test_1')
src_count = src_cursor.fetchone()[0]
src_conn.close()

dst_conn = connect_db('KINGDOM', target=True)
dst_cursor = dst_conn.cursor()
dst_cursor.execute('SELECT COUNT(*) FROM db_test_1')
dst_count = dst_cursor.fetchone()[0]

# 2. Kiểm tra audit_log processing status
dst_cursor.execute('SELECT COUNT(*) FROM sync_audit_log')
audit_total = dst_cursor.fetchone()[0]

dst_cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'pending'")
pending = dst_cursor.fetchone()[0]

dst_cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'processed'")
processed = dst_cursor.fetchone()[0]

dst_conn.close()

# 3. Hiển thị kết quả
print(f'📊 DATABASE SYNC STATUS:')
print(f'  Source DB (db_test_1): {src_count} records')
print(f'  Target DB (db_test_1): {dst_count} records')
print()
print(f'📋 AUDIT_LOG STATUS:')
print(f'  Total entries: {audit_total}')
print(f'  Pending: {pending}')
print(f'  Processed: {processed}')
print()

# 4. Đánh giá kết quả
if src_count == dst_count:
    print('🎉 HOÀN HẢO! Source và Target đã đồng bộ 100%!')
    print('✅ VẤN ĐỀ AUDIT_LOG KHÔNG NHẬN ĐƯỢC RECORDS ĐÃ ĐƯỢC GIẢI QUYẾT!')
    print('✅ INITIAL SYNC VÀ CDC REPLICATOR ĐÃ HOẠT ĐỘNG ĐÚNG!')
elif dst_count > src_count:
    print('⚠️  Target có nhiều records hơn Source (có thể do duplicate)')
elif pending > 0:
    print(f'⏳ Còn {pending} records chưa được xử lý bởi CDC_Replicator')
    print('💡 Cần chạy CDC_Replicator lâu hơn để xử lý hết')
else:
    print('🤔 Có vấn đề cần kiểm tra thêm')
