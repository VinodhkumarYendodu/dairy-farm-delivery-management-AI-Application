"""Document upload, indexing, retrieval, and source-grounded Q&A."""
from fastapi import APIRouter, File, HTTPException, UploadFile

from core.config import get_settings
from integrations.ollama_client import OllamaUnavailableError
from schemas.documents import DocumentQuestion
from services.document_service import DocumentService

router = APIRouter(prefix="/api/v1/documents", tags=["document knowledge base"])


@router.get("")
def list_documents():
    try:
        return DocumentService().list_documents()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Document catalog unavailable; apply migration 006") from exc


@router.post("", status_code=201)
def upload_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=422, detail="A filename is required")
    max_bytes = get_settings().document_max_upload_mb * 1024 * 1024
    try:
        content = file.file.read(max_bytes + 1)
        return DocumentService().ingest(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Local Ollama embedding model is unavailable; the document was not indexed") from exc
    except Exception as exc:
        message = str(exc)
        if "2601" in message or "2627" in message or "duplicate" in message.lower():
            raise HTTPException(status_code=409, detail="This exact document has already been indexed") from exc
        raise HTTPException(status_code=503, detail="Document upload or indexing failed") from exc
    finally:
        file.file.close()


@router.post("/ask")
def ask_documents(item: DocumentQuestion):
    try:
        return DocumentService().ask(item.question)
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Local Ollama model is unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Document search is unavailable") from exc


@router.post("/{document_id}/reindex")
def reindex_document(document_id: int):
    try:
        return DocumentService().reindex(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Local Ollama embedding model is unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Document re-index failed") from exc


@router.delete("/{document_id}")
def delete_document(document_id: int):
    try:
        return DocumentService().delete(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Document deletion failed") from exc
