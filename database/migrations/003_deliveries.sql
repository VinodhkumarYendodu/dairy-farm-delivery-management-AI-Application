IF OBJECT_ID(N'dbo.Deliveries', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Deliveries (
        DeliveryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Deliveries PRIMARY KEY,
        SubscriptionId BIGINT NOT NULL,
        CustomerId INT NOT NULL,
        MilkProductId INT NOT NULL,
        RouteId INT NULL,
        DeliveryDate DATE NOT NULL,
        PlannedQuantity DECIMAL(12,3) NOT NULL,
        DeliveredQuantity DECIMAL(12,3) NULL,
        Status NVARCHAR(30) NOT NULL CONSTRAINT DF_Deliveries_Status DEFAULT ('PLANNED'),
        DeliveredAt DATETIME2(0) NULL,
        Notes NVARCHAR(1000) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Deliveries_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Deliveries_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_Deliveries_Subscriptions FOREIGN KEY (SubscriptionId) REFERENCES dbo.Subscriptions(SubscriptionId),
        CONSTRAINT FK_Deliveries_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT FK_Deliveries_MilkProducts FOREIGN KEY (MilkProductId) REFERENCES dbo.MilkProducts(MilkProductId),
        CONSTRAINT FK_Deliveries_DeliveryRoutes FOREIGN KEY (RouteId) REFERENCES dbo.DeliveryRoutes(RouteId),
        CONSTRAINT CK_Deliveries_PlannedQuantity CHECK (PlannedQuantity > 0),
        CONSTRAINT CK_Deliveries_DeliveredQuantity CHECK (DeliveredQuantity IS NULL OR DeliveredQuantity >= 0),
        CONSTRAINT CK_Deliveries_Status CHECK (Status IN ('PLANNED','OUT_FOR_DELIVERY','DELIVERED','MISSED','CANCELLED')),
        CONSTRAINT UQ_Deliveries_Subscription_Date UNIQUE (SubscriptionId, DeliveryDate)
    );
    CREATE INDEX IX_Deliveries_Date_Route ON dbo.Deliveries(DeliveryDate, RouteId, Status);
    CREATE INDEX IX_Deliveries_Date_Customer ON dbo.Deliveries(DeliveryDate, CustomerId);
    CREATE INDEX IX_Deliveries_Product_Date ON dbo.Deliveries(MilkProductId, DeliveryDate);
END;
GO
