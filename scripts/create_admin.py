"""Create the first administrator account without placing a password in shell history."""
from getpass import getpass
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from database.repositories.auth import AuthRepository
from services.auth_service import hash_password


def start_localdb_if_configured() -> bool:
    server = get_settings().db_server.strip()
    match = re.fullmatch(r"\(localdb\)\\([A-Za-z0-9_.-]+)", server, flags=re.IGNORECASE)
    if not match:
        return True
    try:
        result = subprocess.run(
            ["sqllocaldb", "start", match.group(1)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Could not start LocalDB ({type(exc).__name__}). Run 'sqllocaldb start {match.group(1)}' manually.")
        return False
    if result.returncode:
        print(f"LocalDB start failed (exit code {result.returncode}). Check the instance owner with 'sqllocaldb info {match.group(1)}'.")
        return False
    return True


def main() -> int:
    if not start_localdb_if_configured():
        return 1
    repository = AuthRepository()
    try:
        if repository.has_admin():
            print("An administrator account already exists. Create additional accounts after signing in as an administrator.")
            return 1
    except Exception as exc:
        settings = get_settings()
        if type(exc).__name__ == "OperationalError":
            sqlstate = exc.args[0] if exc.args and re.fullmatch(r"[0-9A-Z]{5}", str(exc.args[0])) else "unknown"
            print(
                f"Could not connect to SQL Server {settings.db_server}, database {settings.db_database}, "
                f"using {settings.db_driver} ({type(exc).__name__}, SQLSTATE {sqlstate}). Run this command as the "
                "same Windows user that owns the LocalDB instance, and verify that the configured ODBC driver is installed."
            )
            print("If this terminal cannot access the LocalDB registry or named pipe, run the command in a regular PowerShell window.")
        else:
            print(
                f"Could not read the account tables ({type(exc).__name__}). "
                "Run: .\\.venv\\Scripts\\python.exe scripts\\migrate_database.py --no-create"
            )
        return 1

    username = input("Administrator username: ").strip()
    password = getpass("Administrator password (12-128 characters): ")
    confirm = getpass("Confirm password: ")
    if not username or len(username) > 80:
        print("Username must contain 1 to 80 characters.")
        return 1
    if not 12 <= len(password) <= 128:
        print("Password must contain 12 to 128 characters.")
        return 1
    if password != confirm:
        print("Passwords did not match.")
        return 1
    salt, password_hash = hash_password(password)
    try:
        repository.create_first_admin(username, salt, password_hash)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"Administrator account {username!r} created. Sign in through the application.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
