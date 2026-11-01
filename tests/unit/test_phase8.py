import pytest

from integrations.ollama_client import OllamaClient
from services.document_ingestion import chunk_document, extract_document
from services.document_service import DocumentService
from core.config import Settings


def test_extract_validates_extension_content_and_credentials():
    ext, text = extract_document("guide.md", b"This is a useful dairy delivery policy for all customers.", 1000)
    assert ext == ".md"
    assert "delivery policy" in text
    with pytest.raises(ValueError, match="Only PDF"):
        extract_document("secret.csv", b"This is enough content for a test document.", 1000)
    with pytest.raises(ValueError, match="credentials"):
        extract_document("notes.txt", b"Password=abc123 this line has enough text for validation.", 1000)


def test_chunking_preserves_overlap_and_all_content():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_document(text, size=200, overlap=30)
    assert len(chunks) > 1
    assert chunks[0][-10:] in chunks[1]
    assert "word499" in chunks[-1]


def test_embedding_client_batches_payload_and_validates_count(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"embeddings": [[1, 2], [3, 4]]}

    calls = []
    monkeypatch.setattr("integrations.ollama_client.httpx.post", lambda url, **kwargs: (calls.append((url, kwargs)) or Response()))
    result = OllamaClient("http://localhost:11434", "llama").embed(["a", "b"], embedding_model="qwen")
    assert result == [[1.0, 2.0], [3.0, 4.0]]
    assert calls[0][1]["json"]["model"] == "qwen"


def test_faiss_retrieval_returns_only_known_source_chunks(tmp_path):
    class Repo:
        def all_chunks(self):
            return [{"id": 1, "document_id": 9, "chunk_number": 0, "text": "milk deliveries occur every morning", "file_name": "policy.md", "file_type": ".md"}]
        def chunks_by_ids(self, ids):
            return [{"id": 1, "document_id": 9, "chunk_number": 0, "text": "milk deliveries occur every morning", "file_name": "policy.md", "file_type": ".md"}] if 1 in ids else []

    class Ollama:
        def embed(self, texts, *, embedding_model):
            return [[1.0, 0.0] for _ in texts]
        def chat(self, messages):
            return "Deliveries occur every morning [S1]."

    settings = Settings(document_storage_path=str(tmp_path / "docs"), faiss_index_path=str(tmp_path / "index"))
    service = DocumentService(settings=settings, repository=Repo(), ollama=Ollama())
    result = service.ask("When do deliveries happen?")
    assert "[S1]" in result["answer"]
    assert result["sources"][0]["file_name"] == "policy.md"


def test_answer_without_valid_citation_is_replaced_with_source_reference(tmp_path):
    class Repo:
        def all_chunks(self):
            return [{"id": 1, "document_id": 9, "chunk_number": 0, "text": "delivery policy text", "file_name": "policy.md", "file_type": ".md"}]
        def chunks_by_ids(self, ids):
            return [{"id": 1, "document_id": 9, "chunk_number": 0, "text": "delivery policy text", "file_name": "policy.md", "file_type": ".md"}]
    class Ollama:
        def embed(self, texts, *, embedding_model):
            return [[1.0, 0.0] for _ in texts]
        def chat(self, messages):
            return "Unsupported unreferenced claim."
    settings = Settings(document_storage_path=str(tmp_path / "docs"), faiss_index_path=str(tmp_path / "index"))
    result = DocumentService(settings=settings, repository=Repo(), ollama=Ollama()).ask("What is the policy?")
    assert "[S1]" in result["answer"]
    assert "Unsupported unreferenced claim" not in result["answer"]


def test_empty_corpus_returns_insufficient_evidence_without_model_call(tmp_path):
    class Repo:
        def all_chunks(self):
            return []
    class Ollama:
        def chat(self, messages):
            raise AssertionError("model should not be called without evidence")
    settings = Settings(document_storage_path=str(tmp_path / "docs"), faiss_index_path=str(tmp_path / "index"))
    result = DocumentService(settings=settings, repository=Repo(), ollama=Ollama()).ask("Some question?")
    assert result == {"answer": "The indexed documents do not contain enough information to answer that question.", "sources": []}
