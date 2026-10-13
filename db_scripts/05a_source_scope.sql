USE [QC];
GO
SET NOCOUNT ON;

SELECT N'INSERT @include (tbl, src_rows) VALUES '
     + STRING_AGG(CAST(N'(N''' + REPLACE(t.name, N'''', N'''''') + N''', '
                       + CAST(ISNULL(r.n, 0) AS NVARCHAR(20)) + N')' AS NVARCHAR(MAX)), N', ')
       WITHIN GROUP (ORDER BY t.name)
     + N';' AS dan_vao_05
FROM sys.tables t
CROSS APPLY (SELECT SUM(ps.row_count) AS n FROM sys.dm_db_partition_stats ps
             WHERE ps.object_id = t.object_id AND ps.index_id IN (0, 1)) r
WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
  AND t.is_ms_shipped = 0
  AND t.name NOT LIKE N'%[_]tracking'
  AND t.name NOT LIKE N'sys%'
  AND t.name NOT LIKE N'MS%'
  AND t.name NOT LIKE N'scope[_]info%'
  AND t.name NOT LIKE N'sync[_]%'
  AND t.name NOT LIKE N'%sync[_]audit[_]log'
  AND t.name NOT IN (N'DMC_NG', N'QC_user', N'Temporary_State_Setting', N'Security');

SELECT t.name AS tbl, r.n AS src_rows
FROM sys.tables t
CROSS APPLY (SELECT SUM(ps.row_count) AS n FROM sys.dm_db_partition_stats ps
             WHERE ps.object_id = t.object_id AND ps.index_id IN (0, 1)) r
WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
  AND t.is_ms_shipped = 0
  AND t.name NOT LIKE N'%[_]tracking'
  AND t.name NOT LIKE N'sys%'
  AND t.name NOT LIKE N'MS%'
  AND t.name NOT LIKE N'scope[_]info%'
  AND t.name NOT LIKE N'sync[_]%'
  AND t.name NOT LIKE N'%sync[_]audit[_]log'
  AND t.name NOT IN (N'DMC_NG', N'QC_user', N'Temporary_State_Setting', N'Security')
ORDER BY r.n DESC;
GO
