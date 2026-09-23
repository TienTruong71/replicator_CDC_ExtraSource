

USE [QC];   
GO
SET NOCOUNT ON;

DECLARE @targets TABLE (tbl SYSNAME);
INSERT INTO @targets (tbl) VALUES
 (N'Castingproduct'),
 (N'Temporary_State_Setting');

DECLARE @tbl SYSNAME, @pk SYSNAME, @sql NVARCHAR(MAX);

DECLARE cur CURSOR LOCAL FAST_FORWARD FOR SELECT tbl FROM @targets;
OPEN cur;
FETCH NEXT FROM cur INTO @tbl;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF OBJECT_ID(N'dbo.' + QUOTENAME(@tbl), N'U') IS NULL
    BEGIN
        PRINT N'SKIP (khong ton tai): ' + @tbl;
        FETCH NEXT FROM cur INTO @tbl; CONTINUE;
    END

    IF EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID(N'dbo.' + QUOTENAME(@tbl))
                 AND name = N'sync_row_id')
    BEGIN
        PRINT N'skip (da co cot sync_row_id): ' + @tbl;
        FETCH NEXT FROM cur INTO @tbl; CONTINUE;
    END

    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'dbo.' + QUOTENAME(@tbl))
                 AND is_primary_key = 1)
    BEGIN
        PRINT N'CANH BAO (bang da co PK, khong dong vao): ' + @tbl;
        FETCH NEXT FROM cur INTO @tbl; CONTINUE;
    END

    SET @sql = N'ALTER TABLE dbo.' + QUOTENAME(@tbl)
             + N' ADD sync_row_id BIGINT IDENTITY(1,1) NOT NULL';
    EXEC sp_executesql @sql;
    PRINT N'ADDED column sync_row_id: ' + @tbl;

    SET @pk = N'PK_' + @tbl + N'_sync';
    SET @sql = N'ALTER TABLE dbo.' + QUOTENAME(@tbl)
             + N' ADD CONSTRAINT ' + QUOTENAME(@pk)
             + N' PRIMARY KEY NONCLUSTERED (sync_row_id)';
    EXEC sp_executesql @sql;
    PRINT N'ADDED PK ' + @pk;

    FETCH NEXT FROM cur INTO @tbl;
END
CLOSE cur; DEALLOCATE cur;
GO

SELECT t.name AS table_name, c.name AS column_name, c.is_identity,
       i.name AS pk_name
FROM sys.tables t
JOIN sys.columns c ON c.object_id = t.object_id AND c.name = N'sync_row_id'
LEFT JOIN sys.indexes i ON i.object_id = t.object_id AND i.is_primary_key = 1
WHERE t.name IN (N'Castingproduct', N'Temporary_State_Setting');
