"""Create a single-file backup of SQL Server and local document/RAG data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from database.connection import sql_connection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _add_tree(archive: zipfile.ZipFile, root: Path, prefix: str, checksums: dict[str, str]) -> None:
    if not root.exists():
        return
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        name = f"{prefix}/{path.relative_to(root).as_posix()}"
        archive.write(path, name)
        checksums[name] = _sha256(path)


def create_backup(output_root: Path | None = None) -> Path:
    settings = get_settings()
    root = (output_root or Path(settings.backup_directory)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = root / f"dairy_backup_{timestamp}.zip"
    database_path = root / f"dairy_database_{timestamp}.bak"
    if archive_path.exists() or database_path.exists():
        raise FileExistsError("A backup with this timestamp already exists; try again in a moment")
    db_name = settings.db_database
    if not db_name.replace("_", "").isalnum() or not db_name[0].isalpha():
        raise ValueError("DB_DATABASE is not a safe SQL Server identifier")
    escaped_path = str(database_path).replace("'", "''")
    try:
        with sql_connection(autocommit=True) as connection:
            cursor = connection.cursor()
            cursor.execute(f"BACKUP DATABASE [{db_name}] TO DISK=N'{escaped_path}' WITH COPY_ONLY,CHECKSUM,INIT,STATS=5")
            while cursor.nextset():
                pass
            cursor.close()
        checksums = {"database.bak": _sha256(database_path)}
        with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_STORED) as archive:
            archive.write(database_path, "database.bak")
            _add_tree(archive, Path(settings.document_storage_path), "documents", checksums)
            _add_tree(archive, Path(settings.faiss_index_path), "faiss_index", checksums)
            _add_tree(archive, Path(settings.customer_issue_storage_path), "customer_issue_photos", checksums)
            manifest = {
                "format_version": 1,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "database_name": db_name,
                "files_sha256": checksums,
            }
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        return archive_path
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        database_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, help="backup directory (default: BACKUP_DIRECTORY)")
    args = parser.parse_args()
    try:
        path = create_backup(args.output_root)
    except Exception as exc:
        print(f"Backup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Backup created: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
