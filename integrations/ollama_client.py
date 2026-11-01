"""Ollama HTTP client. Checks and chat calls never install or pull models."""

from typing import Any

import httpx


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured local Ollama service cannot answer."""


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.8},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise OllamaUnavailableError("Ollama returned an empty response")
            return content.strip()
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError) as exc:
            raise OllamaUnavailableError("Could not get a response from the local Ollama model") from exc

    def embed(self, texts: list[str], *, embedding_model: str) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": embedding_model, "input": texts, "truncate": True},
                timeout=max(self.timeout, 120.0),
            )
            response.raise_for_status()
            embeddings = response.json().get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise OllamaUnavailableError("Ollama returned an invalid embeddings response")
            vectors: list[list[float]] = []
            for vector in embeddings:
                if not isinstance(vector, list) or not vector or any(not isinstance(v, (int, float)) for v in vector):
                    raise OllamaUnavailableError("Ollama returned an invalid embedding vector")
                vectors.append([float(v) for v in vector])
            return vectors
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError) as exc:
            raise OllamaUnavailableError("Could not get embeddings from the local Ollama model") from exc


def check_ollama(base_url: str, required_models: tuple[str, ...], timeout: float = 2.0) -> dict[str, object]:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        installed = {
            item.get("name", "")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        missing = [model for model in required_models if not any(
            name == model or name.startswith(f"{model}:") for name in installed
        )]
        return {
            "status": "ok" if not missing else "models_missing",
            "installed_models": sorted(installed),
            "missing_models": missing,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "unavailable", "detail": str(exc)}

