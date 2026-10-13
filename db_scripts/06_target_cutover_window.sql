/* ============================================================
   06 - CHAY TRONG CUA SO CUTOVER tren DB DICH (8.21 / QC)
   Thu tu: dung tool cu  ->  chay lai 05 (@dry_run = 0, lay delta)
           ->  chay file nay  ->  setup-triggers tool moi.

   A. Restart moi sequence dang lam DEFAULT cho cot khoa (tao boi 01)
      ve MAX(cot)+1. Sequence tao luc tool cu con chay da bi tool cu
      vuot qua (no chen id tuong minh), neu khong restart se cap trung id.
   B. Dem row CHUA gan nhan moi bang - doc metadata, khong quet bang.
      unlabeled phai = 0 (tru row co cot khoa NULL). Neu > 0: chay 05
      voi @sweep = 1 cho bang do roi chay lai B.
   ============================================================ */
USE [QC];
GO
SET NOCOUNT ON;

/* ---------- A. Restart sequence ---------- */
DECLARE @seq NVARCHAR(300), @tbl NVARCHAR(300), @col SYSNAME, @start BIGINT, @sql NVARCHAR(MAX);

DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
    SELECT QUOTENAME(SCHEMA_NAME(s.schema_id)) + N'.' + QUOTENAME(s.name),
           N'dbo.' + QUOTENAME(OBJECT_NAME(dc.parent_object_id)),
           COL_NAME(dc.parent_object_id, dc.parent_column_id)
    FROM sys.default_constraints dc
    JOIN sys.sql_expression_dependencies d ON d.referencing_id = dc.object_id
    JOIN sys.sequences s ON s.object_id = d.referenced_id
    WHERE OBJECT_SCHEMA_NAME(dc.parent_object_id) = N'dbo';
OPEN cur;
FETCH NEXT FROM cur INTO @seq, @tbl, @col;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'SELECT @s = ISNULL(MAX(CONVERT(BIGINT, ' + QUOTENAME(@col) + N')), 0) + 1 FROM ' + @tbl;
    EXEC sp_executesql @sql, N'@s BIGINT OUTPUT', @s = @start OUTPUT;
    SET @sql = N'ALTER SEQUENCE ' + @seq + N' RESTART WITH ' + CAST(@start AS NVARCHAR(20));
    EXEC (@sql);
    PRINT N'RESTART ' + @seq + N' (' + @tbl + N'.' + @col + N') = ' + CAST(@start AS NVARCHAR(20));
    FETCH NEXT FROM cur INTO @seq, @tbl, @col;
END
CLOSE cur; DEALLOCATE cur;

/* ---------- B. Row chua gan nhan ---------- */
SELECT p.tbl,
       a.total_rows,
       ISNULL(b.labeled_rows, 0)                AS labeled_rows,
       a.total_rows - ISNULL(b.labeled_rows, 0) AS unlabeled,
       p.status
FROM dbo.sync_backfill_progress p
CROSS APPLY (SELECT SUM(ps.row_count) FROM sys.dm_db_partition_stats ps
             WHERE ps.object_id = OBJECT_ID(N'dbo.' + QUOTENAME(p.tbl))
               AND ps.index_id IN (0, 1)) a(total_rows)
OUTER APPLY (SELECT SUM(ps.row_count) FROM sys.dm_db_partition_stats ps
             JOIN sys.indexes i ON i.object_id = ps.object_id AND i.index_id = ps.index_id
             WHERE ps.object_id = OBJECT_ID(N'dbo.' + QUOTENAME(p.tbl))
               AND i.name = LEFT(N'UX_' + p.tbl + N'_src', 128)) b(labeled_rows)
ORDER BY unlabeled DESC, p.tbl;
GO
