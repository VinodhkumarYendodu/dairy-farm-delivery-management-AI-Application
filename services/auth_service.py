"""Password verification and opaque session token handling."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import secrets

from database.repositories.auth import AuthRepository, utc_now_naive

PBKDF2_ITERATIONS = 600_000
SESSION_TTL = timedelta(hours=8)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected_hash)


class AuthenticationError(Exception):
    pass


class AuthService:
    def __init__(self, repository: AuthRepository | None = None):
        self.repository = repository or AuthRepository()

    def login(self, username: str, password: str) -> dict:
        user = self.repository.user_for_login(username.strip())
        if not user or not user["is_active"]:
            raise AuthenticationError
        if user["locked_until"] and user["locked_until"] > utc_now_naive():
            raise AuthenticationError
        if not verify_password(password, user["salt"], user["password_hash"]):
            self.repository.record_login_failure(user["id"])
            raise AuthenticationError
        self.repository.clear_login_failures(user["id"])
        token = secrets.token_urlsafe(32)
        expires_at = utc_now_naive() + SESSION_TTL
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        self.repository.create_session(user["id"], token_hash, expires_at)
        return {"access_token": token, "token_type": "bearer", "expires_in": int(SESSION_TTL.total_seconds()),
                "user": {key: user[key] for key in ("id", "username", "role", "customer_id")}}

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create_user(self, username: str, password: str, role: str, customer_id: int | None = None) -> dict:
        username = username.strip()
        if not username or len(username) > 80:
            raise ValueError("Username must contain 1 to 80 characters")
        if len(password) < 12 or len(password) > 128:
            raise ValueError("Password must contain 12 to 128 characters")
        role = role.upper()
        if role not in {"ADMIN", "AGENT", "CUSTOMER"}:
            raise ValueError("Choose ADMIN, AGENT, or CUSTOMER")
        if (role == "CUSTOMER") != (customer_id is not None):
            raise ValueError("Customer accounts require a customer_id; agent accounts must not have one")
        salt, password_hash = hash_password(password)
        try:
            return self.repository.create_user(username, salt, password_hash, role, customer_id)
        except Exception as exc:
            message = str(exc)
            if any(code in message for code in ("23000", "2627", "2601")):
                raise ValueError("Username is already in use or customer already has a login") from exc
            raise

    def register_customer(self, item: dict) -> dict:
        username = item["username"].strip()
        if len(username) < 3 or len(username) > 80:
            raise ValueError("Username must contain 3 to 80 characters")
        if not 12 <= len(item["password"]) <= 128:
            raise ValueError("Password must contain 12 to 128 characters")
        salt, password_hash = hash_password(item["password"])
        try:
            return self.repository.register_customer({**item, "username": username}, salt, password_hash)
        except ValueError:
            raise
        except Exception as exc:
            if any(code in str(exc) for code in ("23000", "2627", "2601")):
                raise ValueError("That username is already in use. Choose another username.") from exc
            raise

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        if not 12 <= len(new_password) <= 128:
            raise ValueError("Password must contain 12 to 128 characters")
        user = self.repository.user_for_login_by_id(user_id)
        if not user or not verify_password(current_password, user["salt"], user["password_hash"]):
            raise AuthenticationError
        salt, password_hash = hash_password(new_password)
        self.repository.update_password(user_id, salt, password_hash)
