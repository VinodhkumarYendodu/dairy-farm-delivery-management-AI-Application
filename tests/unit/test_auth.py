import pytest
from fastapi import HTTPException

from api.auth_dependencies import require_roles
from api.main import app
from services.auth_service import AuthService, AuthenticationError, hash_password, verify_password


def test_password_hash_uses_salt_and_verifies():
    salt, digest = hash_password("a-long-test-password")
    assert len(salt) == 32
    assert len(digest) == 64
    assert verify_password("a-long-test-password", salt, digest)
    assert not verify_password("wrong-password", salt, digest)


def test_customer_role_requires_linked_customer():
    service = AuthService(repository=object())
    with pytest.raises(ValueError, match="customer_id"):
        service.create_user("customer", "a-long-password", "CUSTOMER")
    with pytest.raises(ValueError, match="customer_id"):
        service.create_user("agent", "a-long-password", "AGENT", 7)


def test_account_creation_rejects_short_password_before_database_write():
    service = AuthService(repository=object())
    with pytest.raises(ValueError, match="12 to 128"):
        service.create_user("agent", "short", "AGENT")


def test_login_rejects_invalid_password_and_records_failure():
    class Repository:
        failed = False

        def user_for_login(self, username):
            salt, digest = hash_password("correct-horse-battery")
            return {"id": 1, "username": username, "salt": salt, "password_hash": digest,
                    "role": "AGENT", "customer_id": None, "is_active": True,
                    "failed_count": 0, "locked_until": None}

        def record_login_failure(self, user_id):
            self.failed = user_id == 1

    repository = Repository()
    with pytest.raises(AuthenticationError):
        AuthService(repository).login("agent", "incorrect-password")
    assert repository.failed


def test_login_creates_only_a_hashed_eight_hour_session():
    salt, password_hash = hash_password("correct-horse-battery")

    class Repository:
        session = None

        def user_for_login(self, username):
            return {"id": 4, "username": username, "salt": salt, "password_hash": password_hash,
                    "role": "CUSTOMER", "customer_id": 19, "is_active": True,
                    "failed_count": 0, "locked_until": None}

        def clear_login_failures(self, user_id):
            assert user_id == 4

        def create_session(self, user_id, token_hash, expires_at):
            self.session = (user_id, token_hash, expires_at)

    repository = Repository()
    result = AuthService(repository).login("customer", "correct-horse-battery")
    user_id, stored_hash, expires_at = repository.session
    assert user_id == 4
    assert stored_hash == AuthService.token_hash(result["access_token"])
    assert stored_hash != result["access_token"]
    assert result["user"]["customer_id"] == 19
    assert result["expires_in"] == 8 * 60 * 60


def test_password_change_revokes_sessions_through_repository():
    salt, password_hash = hash_password("current-password-long")

    class Repository:
        updated = None

        def user_for_login_by_id(self, user_id):
            return {"id": user_id, "salt": salt, "password_hash": password_hash}

        def update_password(self, user_id, new_salt, new_hash):
            self.updated = (user_id, verify_password("new-password-long", new_salt, new_hash))

    repository = Repository()
    AuthService(repository).change_password(12, "current-password-long", "new-password-long")
    assert repository.updated == (12, True)


def test_require_roles_blocks_wrong_role_and_allows_matching_role():
    dependency = require_roles("ADMIN")
    with pytest.raises(HTTPException) as exc:
        dependency({"id": 2, "role": "AGENT"})
    assert exc.value.status_code == 403
    user = {"id": 1, "role": "ADMIN"}
    assert dependency(user) is user


def test_business_routes_declare_role_dependencies():
    paths = app.openapi()["paths"]
    assert paths["/api/v1/customers"]["get"]["security"]
    assert paths["/api/v1/auth/login"]["post"].get("security") is None
    assert paths["/api/v1/customer-portal/profile"]["get"]["security"]
