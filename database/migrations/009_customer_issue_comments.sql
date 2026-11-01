IF OBJECT_ID(N'dbo.CustomerIssueComments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CustomerIssueComments (
        CommentId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CustomerIssueComments PRIMARY KEY,
        IssueId BIGINT NOT NULL,
        Author NVARCHAR(100) NOT NULL,
        Comment NVARCHAR(1000) NOT NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_CustomerIssueComments_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_CustomerIssueComments_Issues FOREIGN KEY (IssueId) REFERENCES dbo.CustomerIssues(IssueId)
    );
    CREATE INDEX IX_CustomerIssueComments_Issue_Created
        ON dbo.CustomerIssueComments(IssueId, CreatedAt DESC, CommentId DESC);
END;
GO
