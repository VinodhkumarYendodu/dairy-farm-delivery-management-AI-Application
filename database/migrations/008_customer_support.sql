IF OBJECT_ID(N'dbo.CustomerIssues', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CustomerIssues (
        IssueId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CustomerIssues PRIMARY KEY,
        CustomerId INT NOT NULL,
        Category NVARCHAR(40) NOT NULL,
        Description NVARCHAR(2000) NOT NULL,
        PhotoPath NVARCHAR(1000) NULL,
        PhotoContentType NVARCHAR(40) NULL,
        Status NVARCHAR(20) NOT NULL CONSTRAINT DF_CustomerIssues_Status DEFAULT ('OPEN'),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_CustomerIssues_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_CustomerIssues_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_CustomerIssues_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT CK_CustomerIssues_Category CHECK (Category IN ('DELIVERY','PRODUCT','PAYMENT','ACCOUNT','OTHER')),
        CONSTRAINT CK_CustomerIssues_Status CHECK (Status IN ('OPEN','IN_PROGRESS','RESOLVED','CLOSED'))
    );
    CREATE INDEX IX_CustomerIssues_Customer_Created ON dbo.CustomerIssues(CustomerId, CreatedAt DESC);
    CREATE INDEX IX_CustomerIssues_Status_Created ON dbo.CustomerIssues(Status, CreatedAt DESC);
END;
GO
