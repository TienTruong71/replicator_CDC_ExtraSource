USE [QC];
GO
SET NOCOUNT ON;

SELECT COUNT(*) AS time_trung
FROM (SELECT [Time] FROM dbo.Pallet GROUP BY [Time] HAVING COUNT(*) > 1) x;
GO

BEGIN TRAN;
ALTER TABLE dbo.Pallet DROP CONSTRAINT PK_Pallet;
CREATE CLUSTERED INDEX CX_Pallet_Time ON dbo.Pallet ([Time]);
ALTER TABLE dbo.Pallet ADD id BIGINT IDENTITY(1,1) NOT NULL;
ALTER TABLE dbo.Pallet ADD CONSTRAINT PK_Pallet_id PRIMARY KEY NONCLUSTERED (id);
COMMIT;
GO

SELECT kc.name, kc.type_desc, i.type_desc AS index_type
FROM sys.key_constraints kc
JOIN sys.indexes i ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
WHERE kc.parent_object_id = OBJECT_ID(N'dbo.Pallet');
GO

/*
ROLLBACK:
ALTER TABLE dbo.Pallet DROP CONSTRAINT PK_Pallet_id;
ALTER TABLE dbo.Pallet DROP COLUMN id;
DROP INDEX CX_Pallet_Time ON dbo.Pallet;
ALTER TABLE dbo.Pallet ADD CONSTRAINT PK_Pallet PRIMARY KEY ([Time]);
*/
