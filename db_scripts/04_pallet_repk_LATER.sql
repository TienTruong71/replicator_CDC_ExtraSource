/* ============================================================
   Pallet - doi PRIMARY KEY o CA HAI DAU de chay dung da nguon.
   >>> KHONG CHAY TRONG DOT CUTOVER DAU. Chay sau, rieng biet. <<<

   Van de: Pallet.Time dang la PK o ca nguon lan dich.
     - Insert-only strip PK -> INSERT thieu PK -> fail.
     - Time lam PK toan cuc o dich -> 2 nguon cung thoi diem -> mat dong.

   Muc tieu:
     - NGUON: bo PK Time, them sync_row_id IDENTITY lam PK.
              -> tool strip sync_row_id, luu vao source_record_id, Time chay qua nhu du lieu thuong.
     - DICH : them id IDENTITY lam PK moi, ha Time xuong cot thuong.
              -> dich tu sinh id; chong trung bang (sync_source_id, source_record_id).

   AN TOAN:
     - Backup CA HAI DB truoc khi chay.
     - Dung tool cu / app ghi vao Pallet o ca hai dau.
     - Doi PK la thao tac nang, khoa bang. Chay off-hours.
   Cac phan duoc tach lam 2 block USE - chay dung block cho dung DB.
   ============================================================ */


/* ------------------------------------------------------------
   BLOCK A - chay TREN DB NGUON (QC / moi nguon)
   ------------------------------------------------------------ */
USE [QC];  
GO
SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.Pallet', N'U') IS NULL
    PRINT N'SKIP nguon: bang Pallet khong ton tai';
ELSE
BEGIN
    IF EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID(N'dbo.Pallet') AND name = N'sync_row_id')
        PRINT N'skip nguon (da co sync_row_id)';
    ELSE
    BEGIN
        DECLARE @pkname SYSNAME;
        SELECT @pkname = i.name
        FROM sys.indexes i
        WHERE i.object_id = OBJECT_ID(N'dbo.Pallet') AND i.is_primary_key = 1;

        IF @pkname IS NOT NULL
        BEGIN
            EXEC(N'ALTER TABLE dbo.Pallet DROP CONSTRAINT ' + @pkname);
            PRINT N'DROPPED PK nguon: ' + @pkname;
        END

        ALTER TABLE dbo.Pallet ADD sync_row_id BIGINT IDENTITY(1,1) NOT NULL;
        PRINT N'ADDED sync_row_id (nguon)';

        ALTER TABLE dbo.Pallet
            ADD CONSTRAINT PK_Pallet_sync PRIMARY KEY NONCLUSTERED (sync_row_id);
        PRINT N'ADDED PK_Pallet_sync (nguon)';
    END
END
GO


/* ------------------------------------------------------------
   BLOCK B - chay TREN DB DICH
   ------------------------------------------------------------ */
USE [TARGET_DB];   -- >>> DOI TEN DB DICH <<<
GO
SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.Pallet', N'U') IS NULL
    PRINT N'SKIP dich: bang Pallet khong ton tai';
ELSE
BEGIN
    IF EXISTS (SELECT 1 FROM sys.columns c
               JOIN sys.identity_columns ic ON ic.object_id = c.object_id AND ic.column_id = c.column_id
               WHERE c.object_id = OBJECT_ID(N'dbo.Pallet'))
        PRINT N'skip dich (Pallet da co cot IDENTITY)';
    ELSE
    BEGIN
        DECLARE @pk2 SYSNAME;
        SELECT @pk2 = i.name
        FROM sys.indexes i
        WHERE i.object_id = OBJECT_ID(N'dbo.Pallet') AND i.is_primary_key = 1;

        IF @pk2 IS NOT NULL
        BEGIN
            EXEC(N'ALTER TABLE dbo.Pallet DROP CONSTRAINT ' + @pk2);
            PRINT N'DROPPED PK dich (Time ha xuong cot thuong): ' + @pk2;
        END

        ALTER TABLE dbo.Pallet ADD id BIGINT IDENTITY(1,1) NOT NULL;
        PRINT N'ADDED id IDENTITY (dich)';

        ALTER TABLE dbo.Pallet
            ADD CONSTRAINT PK_Pallet_id PRIMARY KEY NONCLUSTERED (id);
        PRINT N'ADDED PK_Pallet_id (dich)';
    END
END
GO


/* ------------------------------------------------------------
   REVERT (neu can) - chay dung block tren dung DB:
   -- Nguon:
   --   ALTER TABLE dbo.Pallet DROP CONSTRAINT PK_Pallet_sync;
   --   ALTER TABLE dbo.Pallet DROP COLUMN sync_row_id;
   --   ALTER TABLE dbo.Pallet ADD CONSTRAINT PK_Pallet PRIMARY KEY (Time);
   -- Dich:
   --   ALTER TABLE dbo.Pallet DROP CONSTRAINT PK_Pallet_id;
   --   ALTER TABLE dbo.Pallet DROP COLUMN id;
   --   ALTER TABLE dbo.Pallet ADD CONSTRAINT PK_Pallet PRIMARY KEY (Time);
   ------------------------------------------------------------ */
