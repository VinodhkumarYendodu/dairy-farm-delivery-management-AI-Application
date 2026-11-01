CREATE TABLE dbo.NotificationOutbox (
    NotificationId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_NotificationOutbox PRIMARY KEY,
    EventType NVARCHAR(40) NOT NULL,
    DeduplicationKey NVARCHAR(180) NOT NULL,
    RecipientEmail NVARCHAR(320) NULL,
    Subject NVARCHAR(250) NOT NULL,
    TextBody NVARCHAR(MAX) NOT NULL,
    HtmlBody NVARCHAR(MAX) NOT NULL,
    Payload NVARCHAR(MAX) NOT NULL,
    Status NVARCHAR(20) NOT NULL CONSTRAINT DF_NotificationOutbox_Status DEFAULT ('PENDING'),
    Attempts INT NOT NULL CONSTRAINT DF_NotificationOutbox_Attempts DEFAULT (0),
    AvailableAt DATETIME2(0) NOT NULL CONSTRAINT DF_NotificationOutbox_AvailableAt DEFAULT (SYSUTCDATETIME()),
    LeaseUntil DATETIME2(0) NULL,
    LastError NVARCHAR(2000) NULL,
    ProviderResponse NVARCHAR(2000) NULL,
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_NotificationOutbox_CreatedAt DEFAULT (SYSUTCDATETIME()),
    UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_NotificationOutbox_UpdatedAt DEFAULT (SYSUTCDATETIME()),
    LastAttemptAt DATETIME2(0) NULL,
    SentAt DATETIME2(0) NULL,
    CONSTRAINT UQ_NotificationOutbox_DeduplicationKey UNIQUE (DeduplicationKey),
    CONSTRAINT CK_NotificationOutbox_Status CHECK (Status IN ('PENDING','PROCESSING','SENT','FAILED','REQUIRES_REVIEW','SKIPPED')),
    CONSTRAINT CK_NotificationOutbox_Payload CHECK (ISJSON(Payload)=1),
    CONSTRAINT CK_NotificationOutbox_Attempts CHECK (Attempts>=0)
);
CREATE INDEX IX_NotificationOutbox_Queue ON dbo.NotificationOutbox(Status,AvailableAt,CreatedAt);
CREATE INDEX IX_NotificationOutbox_EventType ON dbo.NotificationOutbox(EventType,CreatedAt DESC);
