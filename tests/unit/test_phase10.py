import hashlib
import json
import logging
import zipfile
from pathlib import Path

import pytest

from core.config import Settings
from core.logging_config import configure_logging
from database import connection as db_connection
from scripts import restore_local


def test_settings_reject_nonlocal_ai_workflow_and_unsafe_database_name():
    with pytest.raises(ValueError, match="localhost URL"):
        Settings(ollama_base_url="http://example.com:11434")
    with pytest.raises(ValueError, match="localhost URL"):
        Settings(n8n_webhook_url="https://example.com/webhook")
    with pytest.raises(ValueError, match="simple SQL Server database name"):
        Settings(db_database="Dairy;DROP DATABASE master")


def _make_archive(path: Path, *, member_name: str = "documents/readme.txt", mismatch_checksum: bool = False):
    data = b"local document content"
    backup = b"fake SQL backup payload"
    files = {"database.bak": backup, member_name: data}
    checksums = {name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()}
    if mismatch_checksum:
        checksums["database.bak"] = "0" * 64
    manifest = {"format_version": 1, "created_utc": "2026-10-31T00:00:00+00:00",
                "database_name": "DairySubscriptionDB",
                "files_sha256": checksums}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        archive.writestr("manifest.json", json.dumps(manifest))


def test_restore_archive_checksums_and_uses_separate_data_root(tmp_path, monkeypatch):
    archive = tmp_path / "snapshot.zip"
    _make_archive(archive)
    restored = {}
    monkeypatch.setattr(restore_local, "_restore_database",
        lambda backup, db, folder: restored.update(backup=backup.read_bytes(), database=db, folder=folder))
    output = restore_local.restore_backup(archive, "DairyRestore_01", tmp_path / "new_restore")
    assert (output / "documents" / "readme.txt").read_bytes() == b"local document content"
    assert restored["database"] == "DairyRestore_01"
    assert restored["backup"] == b"fake SQL backup payload"
    assert restored["folder"] == output / "_sql_data"
    with pytest.raises(FileExistsError, match="never overwrites"):
        restore_local.restore_backup(archive, "DairyRestore_01", output)


def test_restore_rejects_traversal_and_detects_corruption(tmp_path):
    traversal = tmp_path / "traversal.zip"
    _make_archive(traversal, member_name="documents/..\\outside.txt")
    with zipfile.ZipFile(traversal) as archive:
        with pytest.raises(ValueError, match="Unsafe backup path"):
            restore_local._verify_archive(archive)

    corrupted = tmp_path / "corrupted.zip"
    _make_archive(corrupted, mismatch_checksum=True)
    with zipfile.ZipFile(corrupted) as archive:
        with pytest.raises(ValueError, match="integrity check failed"):
            restore_local._verify_archive(archive)
    failed_output = tmp_path / "corrupted_restore"
    with pytest.raises(ValueError, match="integrity check failed"):
        restore_local.restore_backup(corrupted, "DairyRestore_02", failed_output)
    assert not failed_output.exists()


def test_rotating_logging_writes_and_rotates_local_files(tmp_path):
    configure_logging("INFO", tmp_path, max_bytes=512, backup_count=2)
    logging.getLogger("phase10.test").info("phase-10-log-marker")
    for number in range(20):
        logging.getLogger("phase10.test").info("rotating-test-line-%s-%s", number, "x" * 80)
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert (tmp_path / "app.log").exists()
    assert (tmp_path / "app.log.1").exists()
    configure_logging("INFO")


def test_sql_health_check_never_returns_raw_connection_errors(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def fail_connection(*args, **kwargs):
        raise RuntimeError("Server=x;PWD=private-secret")
        yield

    monkeypatch.setattr(db_connection, "sql_connection", fail_connection)
    result = db_connection.check_sql_connection(Settings())
    assert result["status"] == "unavailable"
    assert "private-secret" not in result["detail"]
