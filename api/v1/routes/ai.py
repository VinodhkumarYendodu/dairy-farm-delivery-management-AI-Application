"""Read-only AI chat endpoint. The model can only select approved intents."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder

from ai.schemas import AiChatRequest
from core.config import get_settings
from integrations.ollama_client import OllamaClient, OllamaUnavailableError
from services.ai_chat_service import AiChatService

router = APIRouter(prefix="/api/v1/ai", tags=["AI assistant"])


def _json(value):
    return jsonable_encoder(value, custom_encoder={Decimal: lambda amount: format(amount, "f")})


@router.post("/chat")
def chat(item: AiChatRequest):
    settings = get_settings()
    model = OllamaClient(settings.ollama_base_url, settings.ollama_model)
    try:
        return _json(AiChatService(model, settings).ask(item.question))
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail="The local Ollama model is unavailable. Core business operations remain available.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not retrieve the requested business data") from exc
