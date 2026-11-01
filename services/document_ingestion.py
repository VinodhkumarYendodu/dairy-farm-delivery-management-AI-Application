"""Validated extraction, credential screening, and source-aware text chunking."""
from __future__ import annotations

import io
import re
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_TYPES = {".txt", ".md", ".pdf"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(password|passwd|client_secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)AKIA[0-9A-Z]{16}"),
)


def extract_document(filename: str, content: bytes, max_bytes: int) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_TYPES:
        raise ValueError("Only PDF, Markdown, and plain text files are supported")
    if not content:
        raise ValueError("The uploaded file is empty")
    if len(content) > max_bytes:
        raise ValueError(f"The uploaded file exceeds the {max_bytes // (1024 * 1024)} MB limit")
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("The uploaded PDF signature is invalid")
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs cannot be indexed")
            text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Could not read the PDF document") from exc
    else:
        if b"\x00" in content:
            raise ValueError("Binary files are not accepted as text documents")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text documents must use UTF-8 encoding") from exc
    text = text.replace("\x00", "").strip()
    if len(text) < 20:
        raise ValueError("The document contains too little extractable text")
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        raise ValueError("The document appears to contain credentials or a private key and was rejected")
    return extension, text


def chunk_document(text: str, *, size: int = 1200, overlap: int = 160) -> list[str]:
    if size <= overlap or overlap < 0:
        raise ValueError("Chunk size must be greater than non-negative overlap")
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        part = normalized[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks
