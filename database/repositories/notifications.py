"""Transactional outbox persistence and safe dispatch state transitions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import get_settings
from database.connection import sql_connection
from integrations.notification_templates import render_notification


class NotificationRepository:
    @staticmethod
    def enqueue_with_cursor(cursor, event_type: str, deduplication_key: str, recipient: str | None,
                           payload: dict[str, Any]) -> int:
        rendered = render_notification(event_type, payload)
        status = "PENDING" if recipient and recipient.strip() else "SKIPPED"
        error = None if status == "PENDING" else "Customer email is not set"
        cursor.execute(
            "INSERT INTO dbo.NotificationOutbox(EventType,DeduplicationKey,RecipientEmail,Subject,TextBody,HtmlBody,Payload,Status,LastError) "
            "OUTPUT inserted.NotificationId VALUES (?,?,?,?,?,?,?,?,?)",
            event_type, deduplication_key, recipient, rendered["subject"], rendered["text"], rendered["html"],
            json.dumps(payload, ensure_ascii=False, default=str), status, error,
        )
        return int(cursor.fetchone()[0])

    def status(self) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT Status,COUNT_BIG(*) FROM dbo.NotificationOutbox GROUP BY Status")
            counts = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
            cursor.close()
        cfg = get_settings()
        return {"counts": counts, "webhook_configured": bool(cfg.n8n_webhook_url.strip()),
                "n8n_base_url": cfg.n8n_base_url, "dispatch_enabled": bool(cfg.n8n_webhook_url.strip())}

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT TOP (?) NotificationId AS id,EventType AS event_type,DeduplicationKey AS deduplication_key,"
                "RecipientEmail AS recipient_email,Subject AS subject,Status AS status,Attempts AS attempts,"
                "AvailableAt AS available_at,LastAttemptAt AS last_attempt_at,SentAt AS sent_at,LastError AS last_error,"
                "ProviderResponse AS provider_response,CreatedAt AS created_at FROM dbo.NotificationOutbox "
                "WHERE (? IS NULL OR Status=?) ORDER BY CreatedAt DESC,NotificationId DESC", limit, status, status,
            )
            columns = [c[0] for c in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            cursor.close()
            return rows

    def claim_one(self) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            # An expired lease has an uncertain provider outcome. Never resend it automatically.
            cursor.execute("UPDATE dbo.NotificationOutbox SET Status='REQUIRES_REVIEW',LeaseUntil=NULL,LastError=COALESCE(LastError,'Dispatch lease expired; provider outcome is unknown'),UpdatedAt=SYSUTCDATETIME() WHERE Status='PROCESSING' AND LeaseUntil<SYSUTCDATETIME()")
            cursor.execute(
                ";WITH next_item AS (SELECT TOP(1) * FROM dbo.NotificationOutbox WITH (UPDLOCK,READPAST,ROWLOCK) "
                "WHERE Status='PENDING' AND AvailableAt<=SYSUTCDATETIME() AND RecipientEmail IS NOT NULL "
                "ORDER BY AvailableAt,NotificationId) UPDATE next_item SET Status='PROCESSING',Attempts=Attempts+1,"
                "LastAttemptAt=SYSUTCDATETIME(),LeaseUntil=DATEADD(MINUTE,2,SYSUTCDATETIME()),UpdatedAt=SYSUTCDATETIME() "
                "OUTPUT inserted.NotificationId AS id,inserted.RecipientEmail AS recipient,inserted.Subject AS subject,"
                "inserted.TextBody AS text,inserted.HtmlBody AS html,inserted.Attempts AS attempts"
            )
            row = cursor.fetchone()
            result = dict(zip((c[0] for c in cursor.description), row)) if row else None
            connection.commit()
            cursor.close()
            return result

    def mark_sent(self, notification_id: int, response: str) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE dbo.NotificationOutbox SET Status='SENT',SentAt=SYSUTCDATETIME(),UpdatedAt=SYSUTCDATETIME(),LeaseUntil=NULL,LastError=NULL,ProviderResponse=? WHERE NotificationId=? AND Status='PROCESSING'", response[:2000], notification_id)
            connection.commit(); cursor.close()

    def mark_failure(self, notification_id: int, error: str, attempts: int, *, retryable: bool) -> str:
        if retryable and attempts < 5:
            delay = min(60, 2 ** max(1, attempts))
            next_status, available = "PENDING", datetime.now(timezone.utc) + timedelta(minutes=delay)
        else:
            next_status, available = "FAILED", datetime.now(timezone.utc)
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE dbo.NotificationOutbox SET Status=?,AvailableAt=?,UpdatedAt=SYSUTCDATETIME(),LeaseUntil=NULL,LastError=? WHERE NotificationId=? AND Status='PROCESSING'", next_status, available.replace(tzinfo=None), error[:2000], notification_id)
            connection.commit(); cursor.close()
        return next_status

    def require_review(self, notification_id: int, error: str) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE dbo.NotificationOutbox SET Status='REQUIRES_REVIEW',UpdatedAt=SYSUTCDATETIME(),LeaseUntil=NULL,LastError=? WHERE NotificationId=? AND Status='PROCESSING'", error[:2000], notification_id)
            connection.commit(); cursor.close()

    def retry(self, notification_id: int, confirm_possible_duplicate: bool) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT Status FROM dbo.NotificationOutbox WITH (UPDLOCK,HOLDLOCK) WHERE NotificationId=?", notification_id)
            row = cursor.fetchone()
            if not row:
                raise LookupError("Notification not found")
            if row[0] == "REQUIRES_REVIEW" and not confirm_possible_duplicate:
                raise ValueError("Explicitly acknowledge the possibility of a duplicate email before retrying")
            if row[0] not in {"FAILED", "REQUIRES_REVIEW"}:
                raise ValueError("Only failed or review-required notifications can be retried")
            cursor.execute("UPDATE dbo.NotificationOutbox SET Status='PENDING',AvailableAt=SYSUTCDATETIME(),LeaseUntil=NULL,LastError=NULL,UpdatedAt=SYSUTCDATETIME() WHERE NotificationId=?", notification_id)
            connection.commit(); cursor.close()
