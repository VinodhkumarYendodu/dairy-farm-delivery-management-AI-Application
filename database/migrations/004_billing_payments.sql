IF OBJECT_ID(N'dbo.CustomerCharges', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CustomerCharges (
        ChargeId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CustomerCharges PRIMARY KEY,
        CustomerId INT NOT NULL,
        DeliveryId BIGINT NOT NULL,
        ChargeDate DATE NOT NULL,
        Quantity DECIMAL(12,3) NOT NULL,
        UnitPrice DECIMAL(12,2) NOT NULL,
        Amount DECIMAL(14,2) NOT NULL,
        Description NVARCHAR(300) NOT NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_CustomerCharges_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_CustomerCharges_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT FK_CustomerCharges_Deliveries FOREIGN KEY (DeliveryId) REFERENCES dbo.Deliveries(DeliveryId),
        CONSTRAINT CK_CustomerCharges_Quantity CHECK (Quantity > 0),
        CONSTRAINT CK_CustomerCharges_UnitPrice CHECK (UnitPrice >= 0),
        CONSTRAINT CK_CustomerCharges_Amount CHECK (Amount >= 0),
        CONSTRAINT UQ_CustomerCharges_Delivery UNIQUE (DeliveryId)
    );
    CREATE INDEX IX_CustomerCharges_Customer_Date ON dbo.CustomerCharges(CustomerId, ChargeDate, ChargeId);
END;
GO

IF OBJECT_ID(N'dbo.Payments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Payments (
        PaymentId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Payments PRIMARY KEY,
        CustomerId INT NOT NULL,
        PaymentDate DATE NOT NULL,
        Amount DECIMAL(14,2) NOT NULL,
        PaymentMethod NVARCHAR(30) NOT NULL,
        Reference NVARCHAR(100) NULL,
        Notes NVARCHAR(1000) NULL,
        Actor NVARCHAR(100) NOT NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Payments_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_Payments_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT CK_Payments_Amount CHECK (Amount > 0),
        CONSTRAINT CK_Payments_Method CHECK (PaymentMethod IN ('CASH','BANK_TRANSFER','UPI','OTHER'))
    );
    CREATE INDEX IX_Payments_Customer_Date ON dbo.Payments(CustomerId, PaymentDate, PaymentId);
    CREATE INDEX IX_Payments_Date ON dbo.Payments(PaymentDate);
    CREATE UNIQUE INDEX UX_Payments_Reference ON dbo.Payments(Reference) WHERE Reference IS NOT NULL;
END;
GO

IF OBJECT_ID(N'dbo.PaymentAllocations', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.PaymentAllocations (
        AllocationId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_PaymentAllocations PRIMARY KEY,
        PaymentId BIGINT NOT NULL,
        ChargeId BIGINT NOT NULL,
        AllocatedAmount DECIMAL(14,2) NOT NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_PaymentAllocations_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_PaymentAllocations_Payments FOREIGN KEY (PaymentId) REFERENCES dbo.Payments(PaymentId),
        CONSTRAINT FK_PaymentAllocations_Charges FOREIGN KEY (ChargeId) REFERENCES dbo.CustomerCharges(ChargeId),
        CONSTRAINT CK_PaymentAllocations_Amount CHECK (AllocatedAmount > 0),
        CONSTRAINT UQ_PaymentAllocations_Payment_Charge UNIQUE (PaymentId, ChargeId)
    );
    CREATE INDEX IX_PaymentAllocations_Charge ON dbo.PaymentAllocations(ChargeId, AllocationId);
END;
GO

IF OBJECT_ID(N'dbo.CustomerAdjustments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CustomerAdjustments (
        AdjustmentId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CustomerAdjustments PRIMARY KEY,
        CustomerId INT NOT NULL,
        AdjustmentDate DATE NOT NULL,
        EntryType NVARCHAR(20) NOT NULL,
        Direction NVARCHAR(10) NOT NULL,
        Amount DECIMAL(14,2) NOT NULL,
        Reason NVARCHAR(1000) NOT NULL,
        Actor NVARCHAR(100) NOT NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_CustomerAdjustments_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_CustomerAdjustments_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT CK_CustomerAdjustments_Type CHECK (EntryType IN ('ADJUSTMENT','REFUND')),
        CONSTRAINT CK_CustomerAdjustments_Direction CHECK (Direction IN ('DEBIT','CREDIT')),
        CONSTRAINT CK_CustomerAdjustments_Amount CHECK (Amount > 0)
    );
    CREATE INDEX IX_CustomerAdjustments_Customer_Date ON dbo.CustomerAdjustments(CustomerId, AdjustmentDate, AdjustmentId);
END;
GO
