IF OBJECT_ID(N'dbo.AppUsers', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AppUsers (
        UserId INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_AppUsers PRIMARY KEY,
        Username NVARCHAR(80) NOT NULL,
        NormalizedUsername AS UPPER(Username) PERSISTED,
        PasswordSalt CHAR(32) NOT NULL,
        PasswordHash CHAR(64) NOT NULL,
        Role NVARCHAR(20) NOT NULL,
        CustomerId INT NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_AppUsers_IsActive DEFAULT (1),
        FailedLoginCount INT NOT NULL CONSTRAINT DF_AppUsers_FailedLoginCount DEFAULT (0),
        LockedUntil DATETIME2(0) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_AppUsers_CreatedAt DEFAULT (SYSUTCDATETIME()),
        UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_AppUsers_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_AppUsers_NormalizedUsername UNIQUE (NormalizedUsername),
        CONSTRAINT FK_AppUsers_Customers FOREIGN KEY (CustomerId) REFERENCES dbo.Customers(CustomerId),
        CONSTRAINT CK_AppUsers_Role CHECK (Role IN ('ADMIN','AGENT','CUSTOMER')),
        CONSTRAINT CK_AppUsers_CustomerRole CHECK ((Role='CUSTOMER' AND CustomerId IS NOT NULL) OR (Role<>'CUSTOMER' AND CustomerId IS NULL))
    );
    CREATE UNIQUE INDEX UX_AppUsers_CustomerAccount ON dbo.AppUsers(CustomerId) WHERE CustomerId IS NOT NULL;
END;
GO

IF OBJECT_ID(N'dbo.AppSessions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AppSessions (
        SessionId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_AppSessions PRIMARY KEY,
        UserId INT NOT NULL,
        TokenHash CHAR(64) NOT NULL,
        ExpiresAt DATETIME2(0) NOT NULL,
        RevokedAt DATETIME2(0) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_AppSessions_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_AppSessions_TokenHash UNIQUE (TokenHash),
        CONSTRAINT FK_AppSessions_AppUsers FOREIGN KEY (UserId) REFERENCES dbo.AppUsers(UserId)
    );
    CREATE INDEX IX_AppSessions_Active ON dbo.AppSessions(TokenHash, ExpiresAt) INCLUDE (UserId, RevokedAt);
END;
GO
