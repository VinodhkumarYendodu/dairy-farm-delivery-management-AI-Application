"""Reset an existing administrator password and print a one-time temporary credential."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.repositories.auth import AuthRepository
from services.auth_service import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True, help="Existing administrator username")
    username = parser.parse_args().username.strip()
    try:
        user = AuthRepository().user_for_login(username)
        if not user or user["role"] != "ADMIN":
            print("No administrator account was found with that username.")
            return 1
        if not user["is_active"]:
            print("That administrator account is inactive. Activate it before resetting its password.")
            return 1
        temporary_password = secrets.token_urlsafe(18)
        salt, password_hash = hash_password(temporary_password)
        AuthRepository().update_password(user["id"], salt, password_hash)
    except Exception as exc:
        print(f"Password reset failed ({type(exc).__name__}). Verify LocalDB and the account migrations.")
        return 1

    print(f"Administrator: {user['username']}")
    print(f"Temporary password: {temporary_password}")
    print("Sign in once, then change this password from the app's Change password menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
