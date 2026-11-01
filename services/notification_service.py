"""Explicitly triggered delivery of durable notification outbox items."""
from __future__ import annotations

from core.config import get_settings
from database.repositories.notifications import NotificationRepository
from integrations.n8n_client import N8nDispatchError, dispatch_notification


class NotificationService:
    def __init__(self, repository: NotificationRepository | None = None):
        self.repository = repository or NotificationRepository()

    def integration_status(self) -> dict:
        return self.repository.status()

    def list_notifications(self, status: str | None = None, limit: int = 100) -> list[dict]:
        return self.repository.list(status, limit)

    def process_pending(self, limit: int = 20) -> dict:
        cfg = get_settings()
        if not cfg.n8n_webhook_url.strip():
            return {"configured": False, "processed": 0, "message": "N8N_WEBHOOK_URL is not configured"}
        results = []
        for _ in range(limit):
            item = self.repository.claim_one()
            if not item:
                break
            try:
                response = dispatch_notification(cfg.n8n_webhook_url, {
                    "notification_id": item["id"], "to": item["recipient"], "subject": item["subject"],
                    "text": item["text"], "html": item["html"],
                })
                self.repository.mark_sent(item["id"], response)
                results.append({"id": item["id"], "status": "SENT"})
            except N8nDispatchError as exc:
                if exc.outcome_unknown:
                    self.repository.require_review(item["id"], str(exc))
                    state = "REQUIRES_REVIEW"
                else:
                    state = self.repository.mark_failure(item["id"], str(exc), item["attempts"], retryable=exc.retryable)
                results.append({"id": item["id"], "status": state, "error": str(exc)})
        return {"configured": True, "processed": len(results), "results": results}

    def retry(self, notification_id: int, confirm_possible_duplicate: bool) -> dict:
        self.repository.retry(notification_id, confirm_possible_duplicate)
        return {"id": notification_id, "status": "PENDING"}
