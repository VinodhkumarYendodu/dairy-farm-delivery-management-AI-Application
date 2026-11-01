IF OBJECT_ID(N'dbo.DeliveryRoutes', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.DeliveryRoutes (
        RouteId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_DeliveryRoutes PRIMARY KEY,
        RouteName NVARCHAR(100) NOT NULL,
        Description NVARCHAR(500) NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_DeliveryRoutes_IsActive DEFAULT (1),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_DeliveryRoutes_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_DeliveryRoutes_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_DeliveryRoutes_RouteName UNIQUE (RouteName)
    );
END;
GO

IF OBJECT_ID(N'dbo.Customers', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Customers (
        CustomerId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Customers PRIMARY KEY,
        CustomerCode NVARCHAR(30) NOT NULL,
        FullName NVARCHAR(160) NOT NULL,
        Mobile NVARCHAR(30) NOT NULL,
        Email NVARCHAR(254) NULL,
        Address NVARCHAR(500) NOT NULL,
        Area NVARCHAR(100) NULL,
        RouteId INT NULL,
        PreferredContactMethod NVARCHAR(20) NOT NULL CONSTRAINT DF_Customers_Contact DEFAULT ('PHONE'),
        IsActive BIT NOT NULL CONSTRAINT DF_Customers_IsActive DEFAULT (1),
        Notes NVARCHAR(1000) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Customers_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Customers_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_Customers_CustomerCode UNIQUE (CustomerCode),
        CONSTRAINT FK_Customers_DeliveryRoutes FOREIGN KEY (RouteId) REFERENCES dbo.DeliveryRoutes(RouteId),
        CONSTRAINT CK_Customers_Contact CHECK (PreferredContactMethod IN ('PHONE','EMAIL','WHATSAPP','SMS'))
    );
    CREATE INDEX IX_Customers_Name ON dbo.Customers(FullName);
    CREATE INDEX IX_Customers_Route_Active ON dbo.Customers(RouteId, IsActive);
END;
GO

IF OBJECT_ID(N'dbo.MilkProducts', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.MilkProducts (
        MilkProductId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_MilkProducts PRIMARY KEY,
        ProductCode NVARCHAR(30) NOT NULL,
        ProductName NVARCHAR(100) NOT NULL,
        UnitOfMeasure NVARCHAR(20) NOT NULL CONSTRAINT DF_MilkProducts_Unit DEFAULT ('litre'),
        IsActive BIT NOT NULL CONSTRAINT DF_MilkProducts_IsActive DEFAULT (1),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_MilkProducts_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_MilkProducts_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_MilkProducts_ProductCode UNIQUE (ProductCode),
        CONSTRAINT UQ_MilkProducts_ProductName UNIQUE (ProductName)
    );
END;
GO

IF OBJECT_ID(N'dbo.ProductPrices', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ProductPrices (
        ProductPriceId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ProductPrices PRIMARY KEY,
        MilkProductId INT NOT NULL,
        PricePerUnit DECIMAL(12,2) NOT NULL,
        EffectiveFrom DATE NOT NULL,
        EffectiveTo DATE NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_ProductPrices_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_ProductPrices_MilkProducts FOREIGN KEY (MilkProductId) REFERENCES dbo.MilkProducts(MilkProductId),
        CONSTRAINT CK_ProductPrices_Price CHECK (PricePerUnit >= 0),
        CONSTRAINT CK_ProductPrices_Dates CHECK (EffectiveTo IS NULL OR EffectiveTo >= EffectiveFrom),
        CONSTRAINT UQ_ProductPrices_Product_EffectiveFrom UNIQUE (MilkProductId, EffectiveFrom)
    );
    CREATE INDEX IX_ProductPrices_Product_Dates ON dbo.ProductPrices(MilkProductId, EffectiveFrom, EffectiveTo);
END;
GO

IF OBJECT_ID(N'dbo.AuditLogs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AuditLogs (
        AuditLogId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_AuditLogs PRIMARY KEY,
        Actor NVARCHAR(100) NOT NULL,
        Action NVARCHAR(80) NOT NULL,
        EntityType NVARCHAR(80) NOT NULL,
        EntityId NVARCHAR(80) NOT NULL,
        OccurredAt DATETIME2(0) NOT NULL CONSTRAINT DF_AuditLogs_OccurredAt DEFAULT (SYSUTCDATETIME()),
        BeforeSummary NVARCHAR(2000) NULL,
        AfterSummary NVARCHAR(2000) NULL
    );
    CREATE INDEX IX_AuditLogs_Entity ON dbo.AuditLogs(EntityType, EntityId, OccurredAt DESC);
END;
GO

