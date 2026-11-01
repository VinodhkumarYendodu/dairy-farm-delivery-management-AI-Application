"""Customer-submitted support issue persistence."""

from __future__ import annotations

from typing import Any

from database.connection import sql_connection


class CustomerIssueRepository:
    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def create(self, customer_id: int, category: str, description: str,
               photo_path: str | None, photo_content_type: str | None) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO dbo.CustomerIssues(CustomerId,Category,Description,PhotoPath,PhotoContentType) "
                "OUTPUT inserted.IssueId AS id,inserted.Category AS category,inserted.Description AS description,"
                "inserted.Status AS status,inserted.CreatedAt AS created_at "
                "VALUES (?,?,?,?,?)",
                customer_id, category, description, photo_path, photo_content_type,
            )
            row = self._rows(cursor)[0]
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                f"CUSTOMER:{customer_id}", "CUSTOMER_ISSUE_SUBMITTED", "CustomerIssue", str(row["id"]),
                f"category={category}; photo_attached={photo_path is not None}",
            )
            connection.commit()
            cursor.close()
            return {**row, "photo_attached": photo_path is not None}

    def list_for_customer(self, customer_id: int) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT i.IssueId AS id,i.Category AS category,i.Description AS description,"
                "i.PhotoPath AS photo_path,i.Status AS status,i.CreatedAt AS created_at,"
                "comment.Comment AS latest_comment,comment.Author AS latest_comment_by,"
                "comment.CreatedAt AS latest_comment_at "
                "FROM dbo.CustomerIssues i OUTER APPLY ("
                "SELECT TOP(1) Comment,Author,CreatedAt FROM dbo.CustomerIssueComments "
                "WHERE IssueId=i.IssueId ORDER BY CreatedAt DESC,CommentId DESC) comment "
                "WHERE i.CustomerId=? ORDER BY i.CreatedAt DESC,i.IssueId DESC",
                customer_id,
            )
            rows = self._rows(cursor)
            cursor.close()
        for row in rows:
            row["photo_attached"] = row.pop("photo_path") is not None
        return rows

    def list_all(self) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT i.IssueId AS id,c.FullName AS customer_name,c.Mobile AS mobile,"
                "i.Category AS category,i.Description AS description,i.Status AS status,"
                "i.PhotoPath AS photo_path,i.CreatedAt AS created_at,"
                "comment.Comment AS latest_comment,comment.Author AS latest_comment_by,"
                "comment.CreatedAt AS latest_comment_at "
                "FROM dbo.CustomerIssues i JOIN dbo.Customers c ON c.CustomerId=i.CustomerId "
                "OUTER APPLY (SELECT TOP(1) Comment,Author,CreatedAt FROM dbo.CustomerIssueComments "
                "WHERE IssueId=i.IssueId ORDER BY CreatedAt DESC,CommentId DESC) comment "
                "ORDER BY CASE i.Status WHEN 'OPEN' THEN 0 WHEN 'IN_PROGRESS' THEN 1 ELSE 2 END,"
                "i.CreatedAt DESC"
            )
            rows = self._rows(cursor)
            cursor.close()
        for row in rows:
            row["photo_attached"] = row.pop("photo_path") is not None
        return rows

    def photo_path(self, issue_id: int):
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT PhotoPath FROM dbo.CustomerIssues WHERE IssueId=?", issue_id)
            row = cursor.fetchone()
            cursor.close()
        if not row or not row[0]:
            return None
        from pathlib import Path
        from core.config import get_settings

        return Path(get_settings().customer_issue_storage_path).resolve() / row[0]

    def update_status(self, issue_id: int, status: str, comment: str, actor: str) -> dict[str, Any]:
        allowed = {"OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"}
        if status not in allowed:
            raise ValueError("Choose a valid issue status")
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT Status FROM dbo.CustomerIssues WITH (UPDLOCK,HOLDLOCK) WHERE IssueId=?",
                issue_id,
            )
            row = cursor.fetchone()
            if not row:
                cursor.close()
                raise LookupError("Customer issue not found")
            previous = row[0]
            cursor.execute(
                "UPDATE dbo.CustomerIssues SET Status=?,UpdatedAt=SYSUTCDATETIME() WHERE IssueId=?",
                status, issue_id,
            )
            cursor.execute(
                "INSERT INTO dbo.CustomerIssueComments(IssueId,Author,Comment) VALUES (?,?,?)",
                issue_id, actor, comment,
            )
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,BeforeSummary,AfterSummary) "
                "VALUES (?,?,?,?,?,?)",
                actor, "CUSTOMER_ISSUE_STATUS_UPDATED", "CustomerIssue", str(issue_id), previous,
                f"{status}; comment={comment}"[:2000],
            )
            cursor.execute(
                "SELECT UpdatedAt AS updated_at FROM dbo.CustomerIssues WHERE IssueId=?", issue_id,
            )
            updated_at = cursor.fetchone()[0]
            connection.commit()
            cursor.close()
        return {"id": issue_id, "status": status, "previous_status": previous,
                "updated_at": updated_at}
