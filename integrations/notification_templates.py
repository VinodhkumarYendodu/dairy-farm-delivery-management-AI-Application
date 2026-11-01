"""Email copy and rendering, kept separate from transaction logic."""
from __future__ import annotations

import html
from decimal import Decimal
from typing import Any


_COPY = {
    "confirmation_request": ("Please confirm your dairy subscription", "We received your subscription request."),
    "approved": ("Your dairy subscription is approved", "Your subscription has been approved and scheduled."),
    "waitlisted": ("Your dairy subscription needs review", "Some requested delivery dates need availability review."),
    "declined": ("Subscription proposal update", "The subscription proposal was declined."),
    "cancelled": ("Your dairy subscription was cancelled", "Your subscription has been cancelled."),
    "delivery_exception": ("Delivery update", "A delivery could not be completed as planned."),
    "payment_receipt": ("Payment receipt", "We have recorded your payment."),
    "monthly_statement": ("Your monthly dairy statement", "Your account statement is ready."),
}


def render_notification(event_type: str, payload: dict[str, Any]) -> dict[str, str]:
    if event_type not in _COPY:
        raise ValueError(f"Unsupported notification event: {event_type}")
    subject, intro = _COPY[event_type]
    safe = {str(k): str(v) for k, v in payload.items() if v is not None and not isinstance(v, (dict, list, tuple))}
    name = safe.get("customer_name", "Customer")
    details = [f"{key.replace('_', ' ').title()}: {value}" for key, value in safe.items() if key != "customer_name"]
    text = f"Hello {name},\n\n{intro}" + ("\n\n" + "\n".join(details) if details else "") + "\n\nThank you."
    html_details = "".join(f"<li><strong>{html.escape(line.split(': ', 1)[0])}:</strong> {html.escape(line.split(': ', 1)[1])}</li>" for line in details)
    html_body = f"<p>Hello {html.escape(name)},</p><p>{html.escape(intro)}</p>" + (f"<ul>{html_details}</ul>" if details else "") + "<p>Thank you.</p>"
    return {"subject": subject, "text": text, "html": html_body}
