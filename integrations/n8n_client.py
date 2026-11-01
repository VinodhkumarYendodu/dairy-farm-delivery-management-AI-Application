"""HTTP client for a locally configured n8n email workflow."""
from __future__ import annotations

import httpx


class N8nDispatchError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, outcome_unknown: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown


def dispatch_notification(webhook_url: str, notification: dict) -> str:
    try:
        response = httpx.post(webhook_url, json=notification, timeout=30)
    except httpx.ConnectError as exc:
        raise N8nDispatchError("Could not connect to n8n", retryable=True) from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise N8nDispatchError("n8n response was not received; email outcome is unknown", outcome_unknown=True) from exc
    if 200 <= response.status_code < 300:
        return response.text[:2000] or f"HTTP {response.status_code}"
    if response.status_code >= 500:
        raise N8nDispatchError(f"n8n returned HTTP {response.status_code}; email outcome is unknown", outcome_unknown=True)
    raise N8nDispatchError(f"n8n rejected notification with HTTP {response.status_code}: {response.text[:300]}")
