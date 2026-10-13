
USE [QC];
GO
SET NOCOUNT ON;
SET ANSI_NULLS ON; SET ANSI_PADDING ON; SET ANSI_WARNINGS ON;
SET ARITHABORT ON; SET CONCAT_NULL_YIELDS_NULL ON; SET QUOTED_IDENTIFIER ON;
SET NUMERIC_ROUNDABORT OFF;

DECLARE @source_id NVARCHAR(50) = N'192.168.8.59';   
DECLARE @dry_run   BIT = 0;
DECLARE @sweep     BIT = 0;
DECLARE @label     BIT = 0;
DECLARE @batch     INT = 2000;                      
DECLARE @report_every_rows BIGINT = 100000;

DECLARE @include TABLE (tbl SYSNAME PRIMARY KEY, src_rows BIGINT NULL);    
DECLARE @exclude TABLE (tbl SYSNAME PRIMARY KEY);
INSERT @include (tbl, src_rows) VALUES (N'2D_Thread', 7), (N'air_tight', 2042299), (N'air_tight_A2303123', 343456), (N'air_tight_chamfer', 870975), (N'air_tight_collin', 7587), (N'air_tight_detail_A2502179', 6375), (N'air_tight_han', 740), (N'air_tight_spain', 4920), (N'air_tight_standard', 3151), (N'air_tight_window', 17618), (N'airgauge', 1169147), (N'AirGauge_BWMini_Data', 0), (N'AirGauge036', 170982), (N'AirGauge036_Classification', 208235), (N'AirGaugeBW_Mini', 0), (N'Airtight_config', 8), (N'airtight_StrongWay', 150), (N'AirTight036', 156333), (N'BWMini_Data', 0), (N'Castingproduct', 242676), (N'Classification', 2861652), (N'Classification_7075', 18617), (N'Classification_A2303123', 369500), (N'Count_laser', 16), (N'dimension_data', 0), (N'DMC_setup_history', 445), (N'DONG_BIN', 26271), (N'Laser', 2971618), (N'Laser_Original', 919906), (N'Laser_Welding', 0), (N'Master_DMC', 35), (N'Measure_Diameter', 1398244), (N'Measure_Diameter_GC', 63790), (N'MocThuDongHoa', 116), (N'MocThuDongHoaKinKhi', 1587), (N'Pallet', 5940), (N'Scan_Repair_CrossCheck', 0), (N'Scan_Repair_Data', 2932424), (N'Scan_Repair_GTH', 514574), (N'Scan_Repair_KTK', 48534), (N'Scan_Repair_KTR', 543285), (N'Scan_Repair_NQ', 526622), (N'Scan_Repair_PR', 524217), (N'Scan_Repair_Test', 0), (N'ScanQR', 1170544), (N'ScanQR1', 264), (N'Serial_laser', 102), (N'Serial_laser_weekly', 8), (N'Status_Error_Laser', 11), (N'Temporary_State', 4323897), (N'ThreadVerification', 1477450), (N'TiltMeasurement', 226371), (N'TiltMeasurement_delete', 0);
INSERT @exclude VALUES (N'DMC_NG'), (N'QC_user'), (N'Temporary_State_Setting'), (N'Security');

DECLARE @plan TABLE (tbl SYSNAME PRIMARY KEY, object_id INT, key_col SYSNAME NULL, type_name SYSNAME NULL, note NVARCHAR(200), total_rows BIGINT NULL);

INSERT @plan (tbl, object_id, key_col, type_name, note)
SELECT t.name, t.object_id, k.col, k.type_name,
       CASE WHEN k.col IS NULL THEN N'SKIP: khong co cot khoa'
            WHEN k.key_cols > 1 THEN N'SKIP: khoa composite'
            WHEN k.type_name IN (N'tinyint', N'smallint', N'int', N'bigint') THEN N'OK'
            WHEN k.type_name IN (N'datetime', N'smalldatetime', N'datetime2', N'char', N'varchar',
                                 N'nchar', N'nvarchar', N'uniqueidentifier')
                 THEN N'OK-TEXT' + CASE WHEN k.pri = 4 THEN N' (heap, cot dau - phai duy nhat)' ELSE N'' END
            ELSE N'SKIP: kieu khoa chua ho tro (' + k.type_name + N')' END
FROM sys.tables t
OUTER APPLY (
    SELECT TOP (1) x.col, x.key_cols, x.pri, TYPE_NAME(x.user_type_id) AS type_name
    FROM (
        SELECT c.name AS col, c.column_id, c.user_type_id, i.is_primary_key AS is_pk,
               CASE WHEN i.is_primary_key = 1 THEN 1 ELSE 2 END AS pri,
               (SELECT COUNT(*) FROM sys.index_columns ic2
                 WHERE ic2.object_id = i.object_id AND ic2.index_id = i.index_id
                   AND ic2.key_ordinal > 0) AS key_cols
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                                 AND ic.key_ordinal = 1
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE i.object_id = t.object_id
          AND (i.is_primary_key = 1 OR (i.is_unique = 1 AND i.has_filter = 0))
        UNION ALL
        SELECT c.name, c.column_id, c.user_type_id, 0, 3, 1
        FROM sys.columns c
        WHERE c.object_id = t.object_id AND c.name IN (N'id', N'idx')
        UNION ALL
        SELECT c.name, c.column_id, c.user_type_id, 0, 4, 1
        FROM sys.columns c
        WHERE c.object_id = t.object_id
          AND c.name NOT IN (N'sync_source_id', N'source_record_id')
    ) x
    ORDER BY x.pri, x.column_id
) k
WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
  AND t.is_ms_shipped = 0
  AND t.name NOT LIKE N'%[_]tracking'
  AND t.name NOT LIKE N'sys%'
  AND t.name NOT LIKE N'MS%'
  AND t.name NOT LIKE N'scope[_]info%'
  AND t.name NOT LIKE N'sync[_]%'
  AND t.name NOT LIKE N'%sync[_]audit[_]log'
  AND (NOT EXISTS (SELECT 1 FROM @include) OR t.name IN (SELECT tbl FROM @include))
  AND t.name NOT IN (SELECT tbl FROM @exclude);

UPDATE p SET total_rows = r.n
FROM @plan p
CROSS APPLY (SELECT SUM(ps.row_count) AS n FROM sys.dm_db_partition_stats ps
             WHERE ps.object_id = p.object_id AND ps.index_id IN (0, 1)) r;

IF @dry_run = 1
BEGIN
    SELECT p.tbl, p.key_col, p.type_name, p.total_rows AS rows_dich, i.src_rows AS rows_nguon,
           p.total_rows - i.src_rows AS chenh_lech, p.note
    FROM @plan p LEFT JOIN @include i ON i.tbl = p.tbl
    ORDER BY CASE WHEN p.note LIKE N'OK%' THEN 1 ELSE 0 END, p.note, p.tbl;
    SELECT COUNT(*) AS so_bang_se_chay, SUM(total_rows) AS tong_row FROM @plan WHERE note LIKE N'OK%';
    SELECT p.tbl AS dich_it_hon_nguon, p.total_rows AS rows_dich, i.src_rows AS rows_nguon,
           p.total_rows - i.src_rows AS chenh_lech
    FROM @plan p JOIN @include i ON i.tbl = p.tbl
    WHERE p.total_rows < i.src_rows ORDER BY p.total_rows - i.src_rows;
    SELECT i.tbl AS chua_co_tren_dich, i.src_rows FROM @include i
    WHERE OBJECT_ID(N'dbo.' + QUOTENAME(i.tbl), N'U') IS NULL ORDER BY i.tbl;
    PRINT N'DRY RUN - kiem tra danh sach, sua @include/@exclude, roi dat @dry_run = 0.';
    RETURN;
END

IF OBJECT_ID(N'dbo.sync_backfill_progress', N'U') IS NULL
    CREATE TABLE dbo.sync_backfill_progress (
        tbl          SYSNAME       NOT NULL PRIMARY KEY,
        key_col      SYSNAME       NOT NULL,
        last_key     BIGINT        NULL,
        rows_labeled BIGINT        NOT NULL DEFAULT 0,
        status       NVARCHAR(400) NULL,
        updated_at   DATETIME      NOT NULL DEFAULT GETDATE()
    );

DECLARE @tbl SYSNAME, @oid INT, @col SYSNAME, @type SYSNAME, @expr NVARCHAR(400),
        @qt NVARCHAR(300), @qc NVARCHAR(300),
        @ux SYSNAME, @ix SYSNAME, @last BIGINT, @sql NVARCHAR(MAX), @t0 DATETIME,
        @labeled BIGINT, @rows BIGINT, @i INT = 0, @n_tables INT, @all_rows BIGINT,
        @done_rows BIGINT = 0, @run_start DATETIME = GETDATE(), @msg NVARCHAR(2000);

SELECT @n_tables = COUNT(*), @all_rows = ISNULL(SUM(total_rows), 0) FROM @plan WHERE note LIKE N'OK%';
SET @msg = N'BAT DAU: ' + CAST(@n_tables AS NVARCHAR(10)) + N' bang, tong ~' + FORMAT(@all_rows, N'N0') + N' row';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
    SELECT tbl, object_id, key_col, type_name, ISNULL(total_rows, 0) FROM @plan WHERE note LIKE N'OK%' ORDER BY tbl;
OPEN cur;
FETCH NEXT FROM cur INTO @tbl, @oid, @col, @type, @rows;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @qt = N'dbo.' + QUOTENAME(@tbl);
    SET @qc = QUOTENAME(@col);
    SET @ux = LEFT(N'UX_' + @tbl + N'_src', 128);           -- trung ten voi ensure_table_exists
    SET @ix = LEFT(N'IX_' + @tbl + N'_' + @col + N'_sync', 128);
    SET @t0 = GETDATE();
    SET @i += 1;
    SET @msg = N'(' + CAST(@i AS NVARCHAR(10)) + N'/' + CAST(@n_tables AS NVARCHAR(10)) + N') ' + @tbl
             + N' [' + @col + N' ' + @type + N'] ~' + FORMAT(@rows, N'N0') + N' row';
    RAISERROR(@msg, 0, 1) WITH NOWAIT;

    BEGIN TRY
        IF COL_LENGTH(@qt, N'sync_source_id') IS NULL
            EXEC (N'ALTER TABLE ' + @qt + N' ADD [sync_source_id] NVARCHAR(50) NULL');
        IF COL_LENGTH(@qt, N'source_record_id') IS NULL
            EXEC (N'ALTER TABLE ' + @qt + N' ADD [source_record_id] NVARCHAR(100) NULL');

        /* Batch theo khoang khoa can index co cot khoa dung dau, neu khong moi batch quet ca bang. */
        IF @type IN (N'tinyint', N'smallint', N'int', N'bigint')
        AND NOT EXISTS (SELECT 1 FROM sys.index_columns ic
                       WHERE ic.object_id = @oid AND ic.key_ordinal = 1
                         AND COL_NAME(ic.object_id, ic.column_id) = @col)
        BEGIN
            SET @sql = N'CREATE INDEX ' + QUOTENAME(@ix) + N' ON ' + @qt + N' (' + @qc + N')';
            EXEC (@sql);
            SET @msg = N'      + index ' + @ix + N' (' + CAST(DATEDIFF(SECOND, @t0, GETDATE()) AS NVARCHAR(20)) + N's)';
            RAISERROR(@msg, 0, 1) WITH NOWAIT;
        END

        /* Tao truoc khi gan nhan: id trung trong bang heap se bao loi 2601 ngay, khong am tham. */
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = @oid AND name = @ux)
        BEGIN
            SET @sql = N'CREATE UNIQUE INDEX ' + QUOTENAME(@ux) + N' ON ' + @qt
                + N' ([sync_source_id], [source_record_id])'
                + N' WHERE [sync_source_id] IS NOT NULL AND [source_record_id] IS NOT NULL';
            EXEC (@sql);
            SET @msg = N'      + unique index ' + @ux + N' (' + CAST(DATEDIFF(SECOND, @t0, GETDATE()) AS NVARCHAR(20)) + N's)';
            RAISERROR(@msg, 0, 1) WITH NOWAIT;
        END

        IF NOT EXISTS (SELECT 1 FROM dbo.sync_backfill_progress WHERE tbl = @tbl)
            INSERT dbo.sync_backfill_progress (tbl, key_col) VALUES (@tbl, @col);

        IF @label = 0
        BEGIN
            UPDATE dbo.sync_backfill_progress
               SET status = CASE WHEN status = N'done' THEN status ELSE N'ready' END, updated_at = GETDATE()
             WHERE tbl = @tbl;
            SET @done_rows += @rows;
            SET @msg = N'      READY ' + CAST(DATEDIFF(SECOND, @t0, GETDATE()) AS NVARCHAR(20)) + N's | tong: '
                     + FORMAT(@done_rows, N'N0') + N'/' + FORMAT(@all_rows, N'N0') + N' row, '
                     + CAST(DATEDIFF(MINUTE, @run_start, GETDATE()) AS NVARCHAR(20)) + N' phut';
            RAISERROR(@msg, 0, 1) WITH NOWAIT;
            FETCH NEXT FROM cur INTO @tbl, @oid, @col, @type, @rows;
            CONTINUE;
        END

        IF @type NOT IN (N'tinyint', N'smallint', N'int', N'bigint')
        BEGIN
            /* Phai khop chuoi ma upsert_data_odbc tao ra: datetime -> 'yyyy-mm-dd hh:mi:ss.fff',
               chuoi -> trim (rong thi tool coi la NULL), cat 100 ky tu nhu cot dich. */
            SET @expr = CASE
                WHEN @type IN (N'datetime', N'smalldatetime')
                     THEN N'CONVERT(NVARCHAR(23), CAST(' + @qc + N' AS DATETIME2(3)), 121)'
                WHEN @type = N'datetime2'
                     THEN N'LEFT(CONVERT(NVARCHAR(30), ' + @qc + N', 121), 23)'
                WHEN @type = N'uniqueidentifier'
                     THEN N'CAST(' + @qc + N' AS NVARCHAR(36))'
                ELSE N'LEFT(LTRIM(RTRIM(CAST(' + @qc + N' AS NVARCHAR(MAX)))), 100)' END;
            SET @sql = N'UPDATE ' + @qt + N'
                SET [sync_source_id] = @sid, [source_record_id] = ' + @expr + N'
                WHERE [sync_source_id] IS NULL AND ' + @qc + N' IS NOT NULL
                  AND ' + @expr + N' <> N'''';
                SET @labeled = @@ROWCOUNT;';
            SET @labeled = 0;
            EXEC sp_executesql @sql, N'@sid NVARCHAR(50), @labeled BIGINT OUTPUT',
                 @sid = @source_id, @labeled = @labeled OUTPUT;
            UPDATE dbo.sync_backfill_progress
               SET rows_labeled = rows_labeled + @labeled, status = N'done', updated_at = GETDATE()
             WHERE tbl = @tbl;
            SET @done_rows += @rows;
            SET @msg = N'      OK +' + FORMAT(@labeled, N'N0') + N' row, '
                     + CAST(DATEDIFF(SECOND, @t0, GETDATE()) AS NVARCHAR(20)) + N's | tong: '
                     + FORMAT(@done_rows, N'N0') + N'/' + FORMAT(@all_rows, N'N0') + N' row, '
                     + CAST(DATEDIFF(MINUTE, @run_start, GETDATE()) AS NVARCHAR(20)) + N' phut';
            RAISERROR(@msg, 0, 1) WITH NOWAIT;
            FETCH NEXT FROM cur INTO @tbl, @oid, @col, @type, @rows;
            CONTINUE;
        END

        SELECT @last = CASE WHEN @sweep = 1 THEN NULL ELSE last_key END
        FROM dbo.sync_backfill_progress WHERE tbl = @tbl;
        SET @last = ISNULL(@last, -9223372036854775807 - 1);

        SET @sql = N'
            DECLARE @hi BIGINT, @n BIGINT, @total BIGINT = 0, @seen BIGINT = 0, @next_report BIGINT = @every,
                    @t DATETIME = GETDATE(), @m NVARCHAR(400);
            WHILE 1 = 1
            BEGIN
                SET @hi = NULL;
                SELECT @hi = MAX(k) FROM (
                    SELECT TOP (@batch) CONVERT(BIGINT, ' + @qc + N') AS k
                    FROM ' + @qt + N'
                    WHERE ' + @qc + N' > @last
                    ORDER BY ' + @qc + N') x;
                IF @hi IS NULL BREAK;

                UPDATE ' + @qt + N'
                   SET [sync_source_id]   = @sid,
                       [source_record_id] = CAST(' + @qc + N' AS NVARCHAR(100))
                 WHERE ' + @qc + N' > @last AND ' + @qc + N' <= @hi
                   AND [sync_source_id] IS NULL;
                SET @n = @@ROWCOUNT;
                SET @total += @n;
                SET @last = @hi;
                SET @seen += @batch;
                IF @seen >= @next_report
                BEGIN
                    SET @next_report += @every;
                    SET @m = N''      ... '' + @tbl + N'': ~'' + FORMAT(@seen, N''N0'') + N''/'' + FORMAT(@rows, N''N0'')
                           + N'' row, '' + CAST(DATEDIFF(SECOND, @t, GETDATE()) AS NVARCHAR(20)) + N''s, key='' + CAST(@hi AS NVARCHAR(20));
                    RAISERROR(@m, 0, 1) WITH NOWAIT;
                END

                UPDATE dbo.sync_backfill_progress
                   SET last_key = CASE WHEN last_key IS NULL OR last_key < @hi THEN @hi ELSE last_key END,
                       rows_labeled = rows_labeled + @n, status = N''running'', updated_at = GETDATE()
                 WHERE tbl = @tbl;
            END
            SET @labeled = @total;';

        SET @labeled = 0;
        EXEC sp_executesql @sql,
             N'@batch INT, @last BIGINT, @sid NVARCHAR(50), @tbl SYSNAME, @rows BIGINT, @every BIGINT, @labeled BIGINT OUTPUT',
             @batch = @batch, @last = @last, @sid = @source_id, @tbl = @tbl, @rows = @rows,
             @every = @report_every_rows, @labeled = @labeled OUTPUT;

        UPDATE dbo.sync_backfill_progress
           SET status = N'done', updated_at = GETDATE()
         WHERE tbl = @tbl;
        SET @done_rows += @rows;
        SET @msg = N'      OK +' + FORMAT(@labeled, N'N0') + N' row, '
                 + CAST(DATEDIFF(SECOND, @t0, GETDATE()) AS NVARCHAR(20)) + N's | tong: '
                 + FORMAT(@done_rows, N'N0') + N'/' + FORMAT(@all_rows, N'N0') + N' row, '
                 + CAST(DATEDIFF(MINUTE, @run_start, GETDATE()) AS NVARCHAR(20)) + N' phut';
        RAISERROR(@msg, 0, 1) WITH NOWAIT;
    END TRY
    BEGIN CATCH
        SET @done_rows += @rows;
        SET @msg = N'      LOI ' + @tbl + N': ' + REPLACE(ERROR_MESSAGE(), N'%', N'%%');
        RAISERROR(@msg, 0, 1) WITH NOWAIT;
        IF EXISTS (SELECT 1 FROM dbo.sync_backfill_progress WHERE tbl = @tbl)
            UPDATE dbo.sync_backfill_progress
               SET status = LEFT(N'ERROR: ' + ERROR_MESSAGE(), 400), updated_at = GETDATE()
             WHERE tbl = @tbl;
    END CATCH

    FETCH NEXT FROM cur INTO @tbl, @oid, @col, @type, @rows;
END
CLOSE cur; DEALLOCATE cur;

SELECT tbl, key_col, last_key, rows_labeled, status, updated_at
FROM dbo.sync_backfill_progress
ORDER BY CASE WHEN status LIKE N'ERROR%' THEN 0 ELSE 1 END, tbl;
GO
