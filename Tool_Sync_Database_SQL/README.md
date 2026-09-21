## Nếu có sửa lại code thì chạy lệnh sau để build lại file .exe
```
python build_exe.py
```

## Bắt buộc phải để file .env cùng cấp với file CDC_Replicator.exe để chạy chương trình

```
# IP DB nguồn
KINGDOM_SQLSERVER_HOST=
KINGDOM_SQLSERVER_USER=
KINGDOM_SQLSERVER_PASS=
KINGDOM_SQLSERVER_DB=	
KINGDOM_SQLSERVER_PORT=


# IP DB đích
KINGDOM_DST_SQLSERVER_HOST=
KINGDOM_DST_SQLSERVER_USER=
KINGDOM_DST_SQLSERVER_PASS=
KINGDOM_DST_SQLSERVER_DB=
KINGDOM_DST_SQLSERVER_PORT=


# KINGDOM_SYNC_TABLES=                  # Table cụ thể muốn đồng bộ , default: all
KINGDOM_BATCH_SIZE=                     # Tốc độ đồng bộ, default: 500
KINGDOM_SCHEMA_CHECK_INTERVAL=          # Tốc độ check column trong table thay đổi, default: 5s
KINGDOM_TABLE_SCAN_INTERVAL=            # Tốc độ check xem db có table nào thay đổi , default: 5m
```

## Trong trường hợp hi hữu lỡ tay xóa bảng log hoặc khởi động nguội thì chạy lại lệnh sau ở cmd trong folder chứa file .exe để bù đắp dữ liệu
```
CDC_Replicator.exe --sync-missing
```

## Lệnh xóa trigger và bảng log để tool tự động tạo lại phòng trường hợp hệ thống không quét được (... là tên table)
```
DROP TRIGGER IF EXISTS dbo.trig_cdc_...._INS;
TRUNCATE TABLE dbo.sync_audit_log;
```
