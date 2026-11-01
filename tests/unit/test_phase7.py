from integrations.notification_templates import render_notification
from integrations.n8n_client import N8nDispatchError, dispatch_notification
from services.notification_service import NotificationService


def test_template_escapes_customer_values_and_renders_amounts():
    rendered = render_notification("payment_receipt", {"customer_name": "<script>alert(1)</script>", "amount": "12.50"})
    assert "<script>" not in rendered["html"]
    assert "&lt;script&gt;" in rendered["html"]
    assert "12.50" in rendered["text"]


def test_process_is_disabled_without_webhook(monkeypatch):
    class Settings:
        n8n_webhook_url = "  "

    class Repo:
        def claim_one(self):
            raise AssertionError("must not claim when dispatch is not configured")

    monkeypatch.setattr("services.notification_service.get_settings", lambda: Settings())
    result = NotificationService(Repo()).process_pending()
    assert result["configured"] is False
    assert result["processed"] == 0


def test_unknown_provider_outcome_is_not_retryable():
    error = N8nDispatchError("timeout", outcome_unknown=True)
    assert error.outcome_unknown is True
    assert error.retryable is False


def test_workflow_send_http_response_is_explicit(monkeypatch):
    class Response:
        status_code = 202
        text = "accepted"

    monkeypatch.setattr("integrations.n8n_client.httpx.post", lambda *args, **kwargs: Response())
    assert dispatch_notification("http://localhost/webhook", {"to": "test@example.com"}) == "accepted"
