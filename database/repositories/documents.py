"""SQL metadata and chunk persistence for local document retrieval."""
from __future__ import annotations

from typing import Any

from database.connection import sql_connection


class DocumentRepository:
    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def list_documents(self) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT DocumentId AS id,FileName AS file_name,FileType AS file_type,Checksum AS checksum,Status AS status,ChunkCount AS chunk_count,ErrorMessage AS error_message,CreatedAt AS created_at,UpdatedAt AS updated_at FROM dbo.Documents ORDER BY CreatedAt DESC,DocumentId DESC")
            rows = self._rows(cursor)
            cursor.close()
            return rows

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT DocumentId AS id,FileName AS file_name,StoragePath AS storage_path,FileType AS file_type,Checksum AS checksum,Status AS status,ChunkCount AS chunk_count FROM dbo.Documents WHERE DocumentId=?", document_id)
            rows = self._rows(cursor)
            cursor.close()
            return rows[0] if rows else None

    def insert_document(self, filename: str, storage_path: str, file_type: str, checksum: str, chunks: list[str]) -> int:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET XACT_ABORT ON")
            cursor.execute("INSERT INTO dbo.Documents(FileName,StoragePath,FileType,Checksum,Status,ChunkCount) OUTPUT inserted.DocumentId VALUES (?,?,?,?, 'INDEXED',?)", filename, storage_path, file_type, checksum, len(chunks))
            document_id = int(cursor.fetchone()[0])
            for number, text in enumerate(chunks):
                cursor.execute("INSERT INTO dbo.DocumentChunks(DocumentId,ChunkNumber,ChunkText) VALUES (?,?,?)", document_id, number, text)
            connection.commit()
            cursor.close()
            return document_id

    def replace_chunks(self, document_id: int, chunks: list[str]) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET XACT_ABORT ON; DELETE FROM dbo.DocumentChunks WHERE DocumentId=?", document_id)
            for number, text in enumerate(chunks):
                cursor.execute("INSERT INTO dbo.DocumentChunks(DocumentId,ChunkNumber,ChunkText) VALUES (?,?,?)", document_id, number, text)
            cursor.execute("UPDATE dbo.Documents SET Status='INDEXED',ChunkCount=?,ErrorMessage=NULL,UpdatedAt=SYSUTCDATETIME() WHERE DocumentId=?", len(chunks), document_id)
            connection.commit(); cursor.close()

    def mark_failed(self, document_id: int, message: str) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE dbo.Documents SET Status='FAILED',ErrorMessage=?,UpdatedAt=SYSUTCDATETIME() WHERE DocumentId=?", message[:1000], document_id)
            connection.commit(); cursor.close()

    def delete_document(self, document_id: int) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET XACT_ABORT ON; SELECT DocumentId AS id,StoragePath AS storage_path FROM dbo.Documents WITH (UPDLOCK,HOLDLOCK) WHERE DocumentId=?", document_id)
            rows = self._rows(cursor)
            if not rows:
                cursor.close()
                return None
            cursor.execute("DELETE FROM dbo.Documents WHERE DocumentId=?", document_id)
            connection.commit(); cursor.close()
            return rows[0]

    def all_chunks(self) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT ch.ChunkId AS id,ch.DocumentId AS document_id,ch.ChunkNumber AS chunk_number,ch.ChunkText AS text,d.FileName AS file_name,d.FileType AS file_type FROM dbo.DocumentChunks ch JOIN dbo.Documents d ON d.DocumentId=ch.DocumentId WHERE d.Status='INDEXED' ORDER BY ch.ChunkId")
            rows = self._rows(cursor)
            cursor.close()
            return rows

    def chunks_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT ch.ChunkId AS id,ch.DocumentId AS document_id,ch.ChunkNumber AS chunk_number,ch.ChunkText AS text,d.FileName AS file_name,d.FileType AS file_type FROM dbo.DocumentChunks ch JOIN dbo.Documents d ON d.DocumentId=ch.DocumentId WHERE d.Status='INDEXED' AND ch.ChunkId IN (" + placeholders + ")", *ids)
            rows = self._rows(cursor)
            cursor.close()
            return rows
