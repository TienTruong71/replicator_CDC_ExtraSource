
USE [TARGET_DB];  
GO
SET NOCOUNT ON;

DECLARE @tables TABLE (tbl SYSNAME, col SYSNAME);
INSERT INTO @tables (tbl, col) VALUES
 (N'air_tight_collin',            N'ID'),
 (N'air_tight_detail_A2502179',   N'ID'),
 (N'MocThuDongHoaKinKhi',         N'id'),
 (N'ScanQR1',                     N'ID'),
 (N'Temporary_State',             N'id'),
 (N'Serial_laser',                N'id'),
 (N'dimension_data',              N'id');

DECLARE @tbl SYSNAME, @col SYSNAME, @seq SYSNAME, @df SYSNAME, @coltype SYSNAME,
        @start BIGINT, @sql NVARCHAR(MAX);

DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT tbl, col FROM @tables;
OPEN cur;
FETCH NEXT FROM cur INTO @tbl, @col;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF OBJECT_ID(N'dbo.' + QUOTENAME(@tbl), N'U') IS NULL
    BEGIN
        PRINT N'SKIP (khong ton tai): ' + @tbl;
        FETCH NEXT FROM cur INTO @tbl, @col; CONTINUE;
    END

    SET @seq = N'seq_' + @tbl;
    SET @df  = N'DF_' + @tbl + N'_' + @col;

    SELECT @coltype = ty.name
    FROM sys.columns c
    JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    WHERE c.object_id = OBJECT_ID(N'dbo.' + QUOTENAME(@tbl)) AND c.name = @col;

    IF @coltype NOT IN (N'tinyint', N'smallint', N'int', N'bigint')
    BEGIN
        PRINT N'SKIP (cot id khong phai kieu so nguyen: ' + ISNULL(@coltype,N'?')
            + N'): ' + @tbl + N'.' + @col;
        FETCH NEXT FROM cur INTO @tbl, @col; CONTINUE;
    END

    SET @sql = N'SELECT @s = ISNULL(MAX(CONVERT(BIGINT,' + QUOTENAME(@col)
             + N')),0)+1 FROM dbo.' + QUOTENAME(@tbl);
    EXEC sp_executesql @sql, N'@s BIGINT OUTPUT', @s = @start OUTPUT;

    IF NOT EXISTS (SELECT 1 FROM sys.sequences
                   WHERE name = @seq AND schema_id = SCHEMA_ID(N'dbo'))
    BEGIN
        SET @sql = N'CREATE SEQUENCE dbo.' + QUOTENAME(@seq)
                 + N' AS ' + @coltype
                 + N' START WITH ' + CAST(@start AS NVARCHAR(20))
                 + N' INCREMENT BY 1';
        EXEC sp_executesql @sql;
        PRINT N'CREATED sequence ' + @seq + N' AS ' + @coltype
            + N' start=' + CAST(@start AS NVARCHAR(20));
    END
    ELSE
        PRINT N'skip sequence (da co): ' + @seq;

    IF EXISTS (SELECT 1 FROM sys.default_constraints dc
               JOIN sys.columns c ON c.object_id = dc.parent_object_id
                                  AND c.column_id = dc.parent_column_id
               WHERE dc.parent_object_id = OBJECT_ID(N'dbo.' + QUOTENAME(@tbl))
                 AND c.name = @col)
        PRINT N'skip default (cot da co DEFAULT): ' + @tbl + N'.' + @col;
    ELSE
    BEGIN
        SET @sql = N'ALTER TABLE dbo.' + QUOTENAME(@tbl)
                 + N' ADD CONSTRAINT ' + QUOTENAME(@df)
                 + N' DEFAULT (NEXT VALUE FOR dbo.' + QUOTENAME(@seq)
                 + N') FOR ' + QUOTENAME(@col);
        EXEC sp_executesql @sql;
        PRINT N'ADDED default ' + @df;
    END

    FETCH NEXT FROM cur INTO @tbl, @col;
END
CLOSE cur; DEALLOCATE cur;
GO

/* Kiem tra ket qua */
SELECT s.name AS sequence_name, s.current_value
FROM sys.sequences s
WHERE s.name LIKE N'seq_%'
ORDER BY s.name;

SELECT t.name AS table_name, c.name AS column_name, dc.name AS default_name, dc.definition
FROM sys.default_constraints dc
JOIN sys.tables  t ON t.object_id = dc.parent_object_id
JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
WHERE dc.name LIKE N'DF_%'
ORDER BY t.name;
