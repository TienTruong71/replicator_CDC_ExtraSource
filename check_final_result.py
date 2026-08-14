import sys, os
sys.path.insert(0, 'replicator/src')
from db_utils import connect_db
from dotenv import load_dotenv
load_dotenv()

print('📊 KẾT QUẢ ĐỒNG BỘ:')
print('==================')

# 1. Kiểm tra SOURCE DB
print('\n🔹 SOURCE DB (dongbo):')
src_conn = connect_db('KINGDOM', target=False)
src_cursor = src_conn.cursor()

src_cursor.execute('SELECT COUNT(*) FROM db_test_1')
src_count = src_cursor.fetchone()[0]
print(f'  db_test_1: {src_count} records')

src_cursor.execute('SELECT COUNT(*) FROM sync_audit_log')
audit_total = src_cursor.fetchone()[0]
src_cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'pending'")
audit_pending = src_cursor.fetchone()[0]
src_cursor.execute("SELECT COUNT(*) FROM sync_audit_log WHERE status = 'processed'")
audit_processed = src_cursor.fetchone()[0]

print(f'  audit_log: Total={audit_total}, Pending={audit_pending}, Processed={audit_processed}')

src_conn.close()

# 2. Kiểm tra TARGET DB  
print('\n🔹 TARGET DB (Test_extra):')
dst_conn = connect_db('KINGDOM', target=True)
dst_cursor = dst_conn.cursor()

dst_cursor.execute('SELECT COUNT(*) FROM db_test_1')
dst_count = dst_cursor.fetchone()[0]
print(f'  db_test_1: {dst_count} records')

dst_conn.close()

# 3. Đánh giá kết quả
print('\n🎯 ĐÁNH GIÁ:')
print(f'  Source: {src_count} records')
print(f'  Target: {dst_count} records') 
print(f'  Missing: {max(0, src_count - dst_count)} records')

if src_count == dst_count:
    print('\n🎉 HOÀN HẢO! Đồng bộ 100% thành công!')
    print('✅ Source và Target đã có cùng số lượng dữ liệu')
elif dst_count > src_count:
    print(f'\n⚠️  Target có nhiều hơn Source ({dst_count - src_count} records)')
elif audit_pending > 0:
    print(f'\n⏳ Còn {audit_pending} records đang pending (cần chạy CDC_Replicator tiếp)')
else:
    print(f'\n🤔 Vẫn thiếu {src_count - dst_count} records cần kiểm tra')

print(f'\n📈 PROGRESS: {dst_count}/{src_count} ({dst_count/src_count*100:.1f}%)')
