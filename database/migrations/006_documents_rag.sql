CREATE TABLE dbo.Documents (
    DocumentId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Documents PRIMARY KEY,
    FileName NVARCHAR(260) NOT NULL,
    StoragePath NVARCHAR(1000) NOT NULL,
    FileType NVARCHAR(10) NOT NULL,
    Checksum CHAR(64) NOT NULL,
    Status NVARCHAR(20) NOT NULL CONSTRAINT DF_Documents_Status DEFAULT ('INDEXED'),
    ChunkCount INT NOT NULL CONSTRAINT DF_Documents_ChunkCount DEFAULT (0),
    ErrorMessage NVARCHAR(1000) NULL,
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Documents_CreatedAt DEFAULT (SYSUTCDATETIME()),
    UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Documents_UpdatedAt DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_Documents_Checksum UNIQUE (Checksum),
    CONSTRAINT CK_Documents_Status CHECK (Status IN ('INDEXED','FAILED')),
    CONSTRAINT CK_Documents_FileType CHECK (FileType IN ('.txt','.md','.pdf')),
    CONSTRAINT CK_Documents_ChunkCount CHECK (ChunkCount>=0)
);
CREATE INDEX IX_Documents_Status ON dbo.Documents(Status,CreatedAt DESC);

CREATE TABLE dbo.DocumentChunks (
    ChunkId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_DocumentChunks PRIMARY KEY,
    DocumentId BIGINT NOT NULL,
    ChunkNumber INT NOT NULL,
    ChunkText NVARCHAR(MAX) NOT NULL,
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_DocumentChunks_CreatedAt DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT FK_DocumentChunks_Documents FOREIGN KEY (DocumentId) REFERENCES dbo.Documents(DocumentId),
    CONSTRAINT UQ_DocumentChunks_Document_Number UNIQUE(DocumentId,ChunkNumber),
    CONSTRAINT CK_DocumentChunks_ChunkNumber CHECK(ChunkNumber>=0)
);
CREATE INDEX IX_DocumentChunks_Document ON dbo.DocumentChunks(DocumentId,ChunkNumber);
