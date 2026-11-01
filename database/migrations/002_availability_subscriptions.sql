IF OBJECT_ID(N'dbo.DailyAvailability', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.DailyAvailability (
        AvailabilityId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_DailyAvailability PRIMARY KEY,
        AvailabilityDate DATE NOT NULL,
        MilkProductId INT NOT NULL,
        AvailableQuantity DECIMAL(12,3) NOT NULL,
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_DailyAvailability_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_DailyAvailability_MilkProducts FOREIGN KEY (MilkProductId) REFERENCES dbo.MilkProducts(MilkProductId),
        CONSTRAINT CK_DailyAvailability_Quantity CHECK (AvailableQuantity >= 0),
        CONSTRAINT UQ_DailyAvailability_Date_Product UNIQUE (AvailabilityDate, MilkProductId)
    );
    CREATE INDEX IX_DailyAvailability_Product_Date ON dbo.DailyAvailability(MilkProductId, AvailabilityDate);
END;
GO

IF OBJECT_ID(N'dbo.Subscriptions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Subscriptions (
        SubscriptionId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Subscriptions PRIMARY KEY,
        SubscriptionNumber NVARCHAR(40) NOT NULL,
        CustomerId INT NOT NULL,
        MilkProductId INT NOT NULL,
        QuantityPerDelivery DECIMAL(12,3) NOT NULL,
        Frequency NVARCHAR(20) NOT NULL,
        StartDate DATE NOT NULL,
        EndDate DATE NOT NULL,
        Status NVARCHAR(40) NOT NULL,
        ConfirmationStatus NVARCHAR(20) NOT NULL CONSTRAINT DF_Subscriptions_ConfirmationStatus DEFAULT ('PENDING'),
        ConfirmedAt DATETIME2(0) NULL,
        ApprovedAt DATETIME2(0) NULL,
        UnitPriceSnapshot DECIMAL(12,2) NULL,
        Notes NVARCHAR(1000) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Subscriptions_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Subscriptions_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_Subscriptions_Number UNIQUE (SubscriptionNumber),
        CONSTRAINT FK_Subscriptions_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT FK_Subscriptions_MilkProducts FOREIGN KEY (MilkProductId) REFERENCES dbo.MilkProducts(MilkProductId),
        CONSTRAINT CK_Subscriptions_Quantity CHECK (QuantityPerDelivery > 0),
        CONSTRAINT CK_Subscriptions_Dates CHECK (EndDate >= StartDate),
        CONSTRAINT CK_Subscriptions_Frequency CHECK (Frequency IN ('DAILY','SELECTED_DAYS')),
        CONSTRAINT CK_Subscriptions_Status CHECK (Status IN ('PENDING_CUSTOMER_CONFIRMATION','APPROVED','WAITLISTED','REQUIRES_REVIEW','DECLINED','CANCELLED')),
        CONSTRAINT CK_Subscriptions_Confirmation CHECK (ConfirmationStatus IN ('PENDING','CONFIRMED','DECLINED'))
    );
    CREATE INDEX IX_Subscriptions_Product_Status_Dates ON dbo.Subscriptions(MilkProductId, Status, StartDate, EndDate);
    CREATE INDEX IX_Subscriptions_Customer_Status ON dbo.Subscriptions(CustomerId, Status);
END;
GO

IF OBJECT_ID(N'dbo.SubscriptionDays', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.SubscriptionDays (
        SubscriptionDayId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_SubscriptionDays PRIMARY KEY,
        SubscriptionId BIGINT NOT NULL,
        DayOfWeek TINYINT NOT NULL,
        CONSTRAINT FK_SubscriptionDays_Subscriptions FOREIGN KEY (SubscriptionId) REFERENCES dbo.Subscriptions(SubscriptionId),
        CONSTRAINT CK_SubscriptionDays_ISOWeekday CHECK (DayOfWeek BETWEEN 1 AND 7),
        CONSTRAINT UQ_SubscriptionDays_Subscription_Weekday UNIQUE (SubscriptionId, DayOfWeek)
    );
END;
GO

IF OBJECT_ID(N'dbo.SubscriptionStatusHistory', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.SubscriptionStatusHistory (
        HistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_SubscriptionStatusHistory PRIMARY KEY,
        SubscriptionId BIGINT NOT NULL,
        OldStatus NVARCHAR(40) NULL,
        NewStatus NVARCHAR(40) NOT NULL,
        OccurredAt DATETIME2(0) NOT NULL CONSTRAINT DF_SubscriptionStatusHistory_OccurredAt DEFAULT (SYSUTCDATETIME()),
        Actor NVARCHAR(100) NOT NULL,
        Reason NVARCHAR(1000) NULL,
        CONSTRAINT FK_SubscriptionStatusHistory_Subscriptions FOREIGN KEY (SubscriptionId) REFERENCES dbo.Subscriptions(SubscriptionId)
    );
    CREATE INDEX IX_SubscriptionStatusHistory_Subscription_Time ON dbo.SubscriptionStatusHistory(SubscriptionId, OccurredAt DESC);
END;
GO
