from core.config import Settings
from database.connection import build_connection_string


def test_connection_string_uses_windows_auth_without_password() -> None:
    value = build_connection_string(Settings())
    assert "Trusted_Connection=yes" in value
    assert "SELECT" not in value
    assert "password=" not in value.lower()


def test_non_local_bind_is_rejected() -> None:
    try:
        Settings(app_host="0.0.0.0")
    except ValueError:
        return
    raise AssertionError("non-local host should be rejected")

