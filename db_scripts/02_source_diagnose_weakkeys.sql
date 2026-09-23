

USE [QC]; 
GO
SET NOCOUNT ON;

DECLARE @checks TABLE (tbl SYSNAME, keycol SYSNAME);
INSERT INTO @checks (tbl, keycol) VALUES
 (N'Pallet',                  N'Time'),
 (N'Airtight_config',         N'Item'),
 (N'Castingproduct',          N'Castingname'),
 (N'DMC_NG',                  N'MachineNo'),
 (N'Status_Error_Laser',      N'Status_error'),
 (N'Temporary_State_Setting', N'product');

DECLARE @tbl SYSNAME, @col SYSNAME, @sql NVARCHAR(MAX);

DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT tbl, keycol FROM @checks;
OPEN cur;
FETCH NEXT FROM cur INTO @tbl, @col;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF OBJECT_ID(N'dbo.' + QUOTENAME(@tbl), N'U') IS NULL
    BEGIN
        PRINT N'SKIP (khong ton tai): ' + @tbl;
        FETCH NEXT FROM cur INTO @tbl, @col; CONTINUE;
    END

    SET @sql = N'
        SELECT
            ' + N'''' + @tbl + N'''' + N' AS table_name,
            ' + N'''' + @col + N'''' + N' AS key_col,
            COUNT(*)                              AS total_rows,
            COUNT(DISTINCT ' + QUOTENAME(@col) + N') AS distinct_keys,
            SUM(CASE WHEN ' + QUOTENAME(@col) + N' IS NULL THEN 1 ELSE 0 END) AS null_keys,
            CASE
                WHEN COUNT(*) = COUNT(DISTINCT ' + QUOTENAME(@col) + N')
                 AND SUM(CASE WHEN ' + QUOTENAME(@col) + N' IS NULL THEN 1 ELSE 0 END) = 0
                THEN ''OK - duy nhat, sync an toan''
                ELSE ''RISK - co trung/null, dich se bo dong trung''
            END AS verdict
        FROM dbo.' + QUOTENAME(@tbl);
    EXEC sp_executesql @sql;

    FETCH NEXT FROM cur INTO @tbl, @col;
END
CLOSE cur; DEALLOCATE cur;
GO
