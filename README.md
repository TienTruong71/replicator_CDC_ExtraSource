## Check DB for insert_only mode 

USE [DB_NAME];
GO

;WITH keycand AS (
    SELECT t.object_id, c.name AS key_col, c.is_identity, c.is_nullable, c.column_id, 1 AS pri
    FROM sys.tables t
    JOIN sys.indexes i ON i.object_id=t.object_id AND i.is_primary_key=1
    JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
    JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=ic.column_id
    UNION ALL
    SELECT t.object_id, c.name, c.is_identity, c.is_nullable, c.column_id, 2 AS pri
    FROM sys.tables t
    JOIN sys.indexes i ON i.object_id=t.object_id AND i.is_unique=1 AND i.is_primary_key=0
    JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
    JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=ic.column_id
    UNION ALL
    SELECT t.object_id, c.name, c.is_identity, c.is_nullable, c.column_id, 3 AS pri
    FROM sys.tables t
    JOIN sys.columns c ON c.object_id=t.object_id
    WHERE c.name IN ('id','idx')
    UNION ALL
    SELECT t.object_id, c.name, c.is_identity, c.is_nullable, c.column_id, 4 AS pri
    FROM sys.tables t
    JOIN sys.columns c ON c.object_id=t.object_id
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY pri, column_id) AS rn
    FROM keycand
)
SELECT
    t.name AS table_name,
    r.key_col AS resolved_sync_key,
    CASE r.pri WHEN 1 THEN 'PK'
               WHEN 2 THEN 'UNIQUE index'
               WHEN 3 THEN 'named id/idx'
               WHEN 4 THEN 'FIRST COLUMN (risk)' END AS key_source,
    r.is_identity,
    r.is_nullable,
    dc.definition AS default_def,
    CASE
        WHEN r.is_identity = 1        THEN 'OK - IDENTITY'
        WHEN dc.definition IS NOT NULL THEN 'OK - has DEFAULT'
        WHEN r.is_nullable = 1        THEN 'OK - nullable'
        ELSE 'RISK - no auto-gen, NOT NULL'
    END AS insert_only_verdict
FROM sys.tables t
JOIN ranked r ON r.object_id = t.object_id AND r.rn = 1
LEFT JOIN sys.default_constraints dc
       ON dc.parent_object_id = t.object_id AND dc.parent_column_id = r.column_id
WHERE SCHEMA_NAME(t.schema_id) = 'dbo'
ORDER BY insert_only_verdict DESC, key_source, t.name;



## SQL Delete Trigger
SELECT name FROM sys.triggers
WHERE name LIKE 'trig_cdc_%' AND parent_class_desc = 'OBJECT_OR_COLUMN'

DECLARE @sql NVARCHAR(MAX) = ''
SELECT @sql += 'DROP TRIGGER dbo.[' + name + '];' + CHAR(10)
FROM sys.triggers
WHERE name LIKE 'trig_cdc_%' AND parent_class_desc = 'OBJECT_OR_COLUMN'
EXEC sp_executesql @sql


## Check Trigger exist

SELECT
    name,
    OBJECT_NAME(parent_id) AS table_name,
    parent_class_desc
FROM sys.triggers
ORDER BY name;


=============
CDC_Replicator.exe --sync-missing --table WH_Data_Main


CDC_Replicator.exe --sync-missing --table WH_DryRoom_Slot
CDC_Replicator.exe --sync-missing