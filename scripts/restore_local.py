"""Restore a local backup into a new database and separate data directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from database.connection import sql_connection


SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
ALLOWED_TOP_LEVEL = {"manifest.json", "database.bak", "documents", "faiss_index", "customer_issue_photos"}


def _validate_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if ("\\" in name or ":" in name or "\x00" in name or len(name) > 1024 or
            path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in ALLOWED_TOP_LEVEL):
        raise ValueError(f"Unsafe backup path: {name}")
    return path


def _verify_archive(archive: zipfile.ZipFile) -> dict:
    names = archive.namelist()
    if len(names) > 100_000 or sum(item.file_size for item in archive.infolist()) > 100 * 1024**3:
        raise ValueError("Backup archive exceeds the supported size or file-count limit")
    if len(names) != len(set(names)):
        raise ValueError("Backup contains duplicate file paths")
    for info in archive.infolist():
        path = _validate_member(info.filename)
        if path.parts[0] in {"manifest.json", "database.bak"} and len(path.parts) != 1:
            raise ValueError(f"Invalid backup file path: {info.filename}")
        if path.parts[0] in {"documents", "faiss_index", "customer_issue_photos"} and len(path.parts) == 1 and not info.is_dir():
            raise ValueError(f"Backup data root must be a directory: {info.filename}")
        # Reject symbolic links and other special entries.
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if unix_mode and (unix_mode & 0o170000) not in {0, 0o100000, 0o040000}:
            raise ValueError("Backup contains an unsupported special file")
    if "manifest.json" not in names or "database.bak" not in names:
        raise ValueError("Backup is missing its manifest or SQL Server database backup")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format_version") != 1 or not isinstance(manifest.get("files_sha256"), dict):
        raise ValueError("Unsupported or invalid backup manifest")
    expected = manifest["files_sha256"]
    if set(expected) != set(names) - {"manifest.json"}:
        raise ValueError("Backup manifest does not match the archived files")
    for name, checksum in expected.items():
        digest_state = hashlib.sha256()
        with archive.open(name) as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest_state.update(block)
        digest = digest_state.hexdigest()
        if digest != checksum:
            raise ValueError(f"Backup integrity check failed for {name}")
    return manifest


def _sql_literal(value: str) -> str:
    return "N'" + value.replace("'", "''") + "'"


def _restore_database(backup_file: Path, database_name: str, sql_data_dir: Path) -> None:
    settings = get_settings()
    if not SAFE_DATABASE_NAME.fullmatch(database_name):
        raise ValueError("The restore database name must be a simple SQL Server identifier")
    sql_data_dir.mkdir(parents=True, exist_ok=True)
    with sql_connection(settings.model_copy(update={"db_database": "master"}), autocommit=True) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT DB_ID(?)", database_name)
        if cursor.fetchone()[0] is not None:
            raise FileExistsError(f"Database {database_name} already exists; restore will not overwrite it")
        cursor.execute(f"RESTORE FILELISTONLY FROM DISK={_sql_literal(str(backup_file))}")
        columns = [column[0] for column in cursor.description]
        files = [dict(zip(columns, row)) for row in cursor.fetchall()]
        if not files or not any(row.get("Type") == "D" for row in files):
            raise ValueError("SQL Server backup does not contain a data file")
        moves = []
        data_index = log_index = 0
        for item in files:
            if item["Type"] == "D":
                data_index += 1
                suffix = ".mdf" if data_index == 1 else f"_{data_index}.ndf"
                dest = sql_data_dir / f"{database_name}{suffix}"
            elif item["Type"] == "L":
                log_index += 1
                suffix = ".ldf" if log_index == 1 else f"_log{log_index}.ldf"
                dest = sql_data_dir / f"{database_name}{suffix}"
            else:
                continue
            moves.append(f"MOVE {_sql_literal(str(item['LogicalName']))} TO {_sql_literal(str(dest))}")
        if not moves:
            raise ValueError("SQL Server backup has no restorable data or log files")
        sql = f"RESTORE DATABASE [{database_name}] FROM DISK={_sql_literal(str(backup_file))} WITH " + ",".join(moves) + ",RECOVERY,CHECKSUM,STATS=5"
        cursor.execute(sql)
        while cursor.nextset():
            pass
        cursor.close()


def restore_backup(backup_path: Path, database_name: str, output_root: Path | None = None) -> Path:
    backup_path = backup_path.resolve()
    if not backup_path.is_file():
        raise FileNotFoundError("Backup archive does not exist")
    restore_root = (output_root or backup_path.with_name(f"{backup_path.stem}_restore")).resolve()
    if restore_root.exists():
        raise FileExistsError("Restore output folder already exists; restore never overwrites existing files")
    with zipfile.ZipFile(backup_path, "r") as archive:
        _verify_archive(archive)
        restore_root.mkdir(parents=True, exist_ok=False)
        try:
            for info in archive.infolist():
                path = _validate_member(info.filename)
                if path.parts[0] == "manifest.json":
                    continue
                destination = restore_root.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                with archive.open(info) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
            _restore_database(restore_root / "database.bak", database_name, restore_root / "_sql_data")
            return restore_root
        except Exception:
            # Preserve the extracted backup for diagnosis/retry; never remove data automatically.
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="ZIP created by scripts/backup_local.py")
    parser.add_argument("--database-name", required=True, help="new restore database name; existing databases are never overwritten")
    parser.add_argument("--output-root", type=Path, help="new folder for restored local data (default: beside the backup)")
    args = parser.parse_args()
    try:
        path = restore_backup(args.backup, args.database_name, args.output_root)
    except Exception as exc:
        print(f"Restore failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Restored database: {args.database_name}")
    print(f"Restored local files: {path}")
    print("The running .env was not changed. Review the restored files and database before switching application settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
