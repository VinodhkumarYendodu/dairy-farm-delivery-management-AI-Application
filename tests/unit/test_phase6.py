from datetime import date
from decimal import Decimal

import pytest

from ai.intent_router import classify_question
from ai.schemas import IntentPlan
from core.config import Settings
from integrations.ollama_client import OllamaClient, OllamaUnavailableError
from services.ai_chat_service import AiChatService
from services.reporting_service import ReportingService, month_range


class FakeModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.messages = []

    def chat(self, messages, *, json_mode=False):
        self.messages.append((messages, json_mode))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_intent_plan_rejects_unapproved_fields_and_invalid_dates():
    with pytest.raises(ValueError):
        IntentPlan.model_validate({"intent": "today_demand", "sql": "SELECT * FROM Customers"})
    with pytest.raises(ValueError):
        IntentPlan(intent="monthly_charges", period="CUSTOM", from_date=date(2026, 11, 2), through_date=date(2026, 11, 1))


def test_classifier_maps_malformed_or_sql_like_output_to_unsupported():
    today = date(2026, 11, 10)
    malformed = classify_question("show customers", today, FakeModel("not json"))
    sql_plan = classify_question("show customers", today, FakeModel(
        '{"intent":"today_demand","sql":"SELECT * FROM Customers"}'
    ))
    assert malformed.intent == "unsupported"
    assert sql_plan.intent == "unsupported"


def test_classifier_returns_only_allowlisted_intent_parameters():
    model = FakeModel('{"intent":"today_demand","product":"COW","period":null,"from_date":null,"through_date":null}')
    plan = classify_question("How much cow milk is needed today?", date(2026, 11, 10), model)
    assert plan.intent == "today_demand"
    assert plan.product == "COW"
    assert model.messages[0][1] is True


def test_month_range_handles_january_year_boundary():
    assert month_range(date(2027, 1, 6), "LAST_MONTH") == (date(2026, 12, 1), date(2026, 12, 31))
    assert month_range(date(2027, 1, 6), "THIS_MONTH") == (date(2027, 1, 1), date(2027, 1, 31))


def test_today_demand_counts_only_approved_scheduled_weekdays():
    class Master:
        def list_products(self, active=True):
            return [{"id": 1, "product_code": "COW", "product_name": "Cow Milk", "unit_of_measure": "litre"}]

    class Subs:
        def list_subscriptions(self, status=None):
            return [
                {"product_id": 1, "quantity_per_delivery": Decimal("2.000"), "frequency": "DAILY",
                 "start_date": date(2026, 11, 1), "end_date": date(2026, 11, 30), "selected_days": []},
                {"product_id": 1, "quantity_per_delivery": Decimal("1.500"), "frequency": "SELECTED_DAYS",
                 "start_date": date(2026, 11, 1), "end_date": date(2026, 11, 30), "selected_days": [2]},
                {"product_id": 1, "quantity_per_delivery": Decimal("8.000"), "frequency": "SELECTED_DAYS",
                 "start_date": date(2026, 11, 1), "end_date": date(2026, 11, 30), "selected_days": [1]},
            ]

    service = ReportingService(master=Master(), subscriptions=Subs(), deliveries=object(), billing=object())
    result = service.execute(IntentPlan(intent="today_demand"), date(2026, 11, 10))  # Tuesday
    assert result["products"][0]["required_quantity"] == Decimal("3.500")


def test_reporting_defaults_monthly_charges_to_previous_calendar_month():
    class Billing:
        def list_charges(self, start=None, end=None, **kwargs):
            assert (start, end) == (date(2026, 10, 1), date(2026, 10, 31))
            return [{"amount": Decimal("10.25")}, {"amount": Decimal("4.75")}]

    service = ReportingService(master=object(), subscriptions=object(), deliveries=object(), billing=Billing())
    result = service.execute(IntentPlan(intent="monthly_charges"), date(2026, 11, 10))
    assert result["charge_count"] == 2
    assert result["total_charges"] == Decimal("15.00")
    assert "excludes payments" in result["basis"]


def test_pending_confirmation_report_drops_unneeded_notes():
    class Subs:
        def list_subscriptions(self, status=None):
            return [{"subscription_number": "SUB-1", "customer_name": "A", "product_name": "Cow Milk",
                     "quantity_per_delivery": Decimal("1.000"), "frequency": "DAILY",
                     "start_date": date(2026, 11, 1), "end_date": date(2026, 11, 30),
                     "status": "PENDING_CUSTOMER_CONFIRMATION", "notes": "Private note"}]

    service = ReportingService(master=object(), subscriptions=Subs(), deliveries=object(), billing=object())
    result = service.execute(IntentPlan(intent="pending_confirmations"), date(2026, 11, 10))
    assert result["count"] == 1
    assert "notes" not in result["subscriptions"][0]


def test_route_volumes_are_grouped_by_route_and_unit():
    class Deliveries:
        def list_deliveries(self, start, end, status=None):
            assert status == "DELIVERED"
            return [
                {"route_name": "North", "unit_of_measure": "litre", "delivered_quantity": Decimal("2.000"), "planned_quantity": Decimal("2.000")},
                {"route_name": "North", "unit_of_measure": "litre", "delivered_quantity": Decimal("1.500"), "planned_quantity": Decimal("1.500")},
                {"route_name": "North", "unit_of_measure": "bottle", "delivered_quantity": Decimal("4.000"), "planned_quantity": Decimal("4.000")},
            ]

    service = ReportingService(master=object(), subscriptions=object(), deliveries=Deliveries(), billing=object())
    result = service.execute(IntentPlan(intent="route_volume", period="THIS_MONTH"), date(2026, 11, 10))
    assert len(result["routes"]) == 2
    assert {row["unit"] for row in result["routes"]} == {"litre", "bottle"}
    assert next(row for row in result["routes"] if row["unit"] == "litre")["delivered_quantity"] == Decimal("3.500")


def test_ai_service_returns_structured_data_and_uses_untrusted_data_prompt():
    model = FakeModel(
        '{"intent":"active_subscriptions","product":null,"period":null,"from_date":null,"through_date":null}',
        "There are 3 currently active subscriptions.",
    )

    class Reports:
        def execute(self, plan, today):
            assert plan.intent == "active_subscriptions"
            return {"as_of": today, "count": 3}

    service = AiChatService(model, Settings(app_timezone="UTC"), Reports())
    result = service.ask("How many subscriptions are active?")
    assert result["data"]["count"] == 3
    assert result["answer"].startswith("There are 3")
    assert "untrusted data" in model.messages[1][0][0]["content"]


def test_unsupported_intent_does_not_run_report_or_make_second_model_call():
    model = FakeModel('{"intent":"unsupported","product":null,"period":null,"from_date":null,"through_date":null}')

    class Reports:
        def execute(self, plan, today):
            raise AssertionError("Unsupported intent must not query business data")

    service = AiChatService(model, Settings(app_timezone="UTC"), Reports())
    assert service.ask("delete every customer") ["intent"] == "unsupported"
    assert len(model.messages) == 1


def test_ai_answer_generation_falls_back_to_structured_data_if_ollama_drops():
    model = FakeModel(
        '{"intent":"active_subscriptions","product":null,"period":null,"from_date":null,"through_date":null}',
        OllamaUnavailableError("offline"),
    )

    class Reports:
        def execute(self, plan, today):
            return {"count": 2}

    result = AiChatService(model, Settings(app_timezone="UTC"), Reports()).ask("Count active subscriptions")
    assert "See the structured result" in result["answer"]
    assert result["data"] == {"count": 2}


def test_ollama_client_reports_unavailable_without_raising_raw_http_details(monkeypatch):
    def fail(*args, **kwargs):
        import httpx

        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("integrations.ollama_client.httpx.post", fail)
    client = OllamaClient("http://localhost:11434", "llama3.2:3b", timeout=0.1)
    with pytest.raises(OllamaUnavailableError, match="local Ollama"):
        client.chat([{"role": "user", "content": "test"}])


def test_ollama_client_uses_chat_endpoint_and_structured_json_mode(monkeypatch):
    recorded = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"intent":"unsupported"}'}}

    def fake_post(url, *, json, timeout):
        recorded.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("integrations.ollama_client.httpx.post", fake_post)
    client = OllamaClient("http://localhost:11434/", "llama3.2:3b", timeout=5)
    content = client.chat([{"role": "user", "content": "question"}], json_mode=True)
    assert content == '{"intent":"unsupported"}'
    assert recorded["url"] == "http://localhost:11434/api/chat"
    assert recorded["payload"]["format"] == "json"
    assert recorded["payload"]["stream"] is False
