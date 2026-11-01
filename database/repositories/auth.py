"""SQL Server persistence for application accounts and opaque bearer sessions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database.connection import sql_connection


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthRepository:
    @staticmethod
    def _user(row: Any) -> dict[str, Any]:
        return {"id": row[0], "username": row[1], "role": row[2], "customer_id": row[3],
                "is_active": bool(row[4])}

    def has_admin(self) -> bool:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT TOP (1) 1 FROM dbo.AppUsers WHERE Role='ADMIN' AND IsActive=1")
            found = cursor.fetchone() is not None
            cursor.close()
            return found

    def create_first_admin(self, username: str, salt: str, password_hash: str) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT UserId FROM dbo.AppUsers WITH (UPDLOCK,HOLDLOCK) WHERE Role='ADMIN'")
            if cursor.fetchone():
                connection.rollback()
                raise ValueError("An administrator account already exists")
            cursor.execute(
                "INSERT INTO dbo.AppUsers(Username,PasswordSalt,PasswordHash,Role) VALUES (?,?,?,'ADMIN')",
                username, salt, password_hash,
            )
            connection.commit()
            cursor.close()

    def register_customer(self, item: dict[str, Any], salt: str, password_hash: str) -> dict[str, Any]:
        """Create the customer profile and its login in one SQL transaction."""
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            customer_code = "WEB-" + uuid4().hex[:20].upper()
            cursor.execute(
                "INSERT INTO dbo.Customers(CustomerCode,FullName,Mobile,Email,Address,Area,PreferredContactMethod) "
                "OUTPUT inserted.CustomerId VALUES (?,?,?,?,?,?,?)",
                customer_code, item["full_name"], item["mobile"], item.get("email"),
                item["address"], item.get("area"), "PHONE",
            )
            customer_id = int(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO dbo.AppUsers(Username,PasswordSalt,PasswordHash,Role,CustomerId) "
                "OUTPUT inserted.UserId,inserted.Username,inserted.Role,inserted.CustomerId,inserted.IsActive "
                "VALUES (?,?,?,'CUSTOMER',?)",
                item["username"], salt, password_hash, customer_id,
            )
            user = self._user(cursor.fetchone())
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                item["username"], "CUSTOMER_SIGNUP", "Customer", str(customer_id),
                f"Self-service account created; customer_code={customer_code}",
            )
            connection.commit()
            cursor.close()
            return user

    def create_user(self, username: str, salt: str, password_hash: str, role: str,
                    customer_id: int | None = None) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO dbo.AppUsers(Username,PasswordSalt,PasswordHash,Role,CustomerId) "
                "OUTPUT inserted.UserId,inserted.Username,inserted.Role,inserted.CustomerId,inserted.IsActive "
                "VALUES (?,?,?,?,?)", username, salt, password_hash, role, customer_id,
            )
            user = self._user(cursor.fetchone())
            connection.commit()
            cursor.close()
            return user

    def user_for_login(self, username: str) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT UserId,Username,PasswordSalt,PasswordHash,Role,CustomerId,IsActive,FailedLoginCount,LockedUntil "
                "FROM dbo.AppUsers WHERE NormalizedUsername=UPPER(?)", username,
            )
            row = cursor.fetchone()
            cursor.close()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "salt": row[2], "password_hash": row[3],
                "role": row[4], "customer_id": row[5], "is_active": bool(row[6]),
                "failed_count": row[7], "locked_until": row[8]}

    def user_for_login_by_id(self, user_id: int) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT UserId,Username,PasswordSalt,PasswordHash,Role,CustomerId,IsActive,FailedLoginCount,LockedUntil "
                "FROM dbo.AppUsers WHERE UserId=?", user_id,
            )
            row = cursor.fetchone()
            cursor.close()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "salt": row[2], "password_hash": row[3],
                "role": row[4], "customer_id": row[5], "is_active": bool(row[6]),
                "failed_count": row[7], "locked_until": row[8]}

    def record_login_failure(self, user_id: int) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE dbo.AppUsers SET FailedLoginCount=CASE WHEN FailedLoginCount>=4 THEN 0 ELSE FailedLoginCount+1 END, "
                "LockedUntil=CASE WHEN FailedLoginCount>=4 THEN DATEADD(minute,15,SYSUTCDATETIME()) ELSE LockedUntil END, "
                "UpdatedAt=SYSUTCDATETIME() WHERE UserId=?", user_id,
            )
            connection.commit()
            cursor.close()

    def clear_login_failures(self, user_id: int) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE dbo.AppUsers SET FailedLoginCount=0,LockedUntil=NULL,UpdatedAt=SYSUTCDATETIME() WHERE UserId=?",
                user_id,
            )
            connection.commit()
            cursor.close()

    def create_session(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM dbo.AppSessions WHERE ExpiresAt<SYSUTCDATETIME() OR RevokedAt IS NOT NULL")
            cursor.execute("INSERT INTO dbo.AppSessions(UserId,TokenHash,ExpiresAt) VALUES (?,?,?)",
                           user_id, token_hash, expires_at)
            connection.commit()
            cursor.close()

    def resolve_session(self, token_hash: str) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT u.UserId,u.Username,u.Role,u.CustomerId,u.IsActive "
                "FROM dbo.AppSessions s JOIN dbo.AppUsers u ON u.UserId=s.UserId "
                "LEFT JOIN dbo.Customers c ON c.CustomerId=u.CustomerId "
                "WHERE s.TokenHash=? AND s.RevokedAt IS NULL AND s.ExpiresAt>SYSUTCDATETIME() "
                "AND u.IsActive=1 AND (u.Role<>'CUSTOMER' OR c.IsActive=1)", token_hash,
            )
            row = cursor.fetchone()
            cursor.close()
        return self._user(row) if row else None

    def revoke_session(self, token_hash: str) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE dbo.AppSessions SET RevokedAt=SYSUTCDATETIME() WHERE TokenHash=? AND RevokedAt IS NULL",
                           token_hash)
            connection.commit()
            cursor.close()

    def list_users(self) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT u.UserId AS id,u.Username AS username,u.Role AS role,u.CustomerId AS customer_id,"
                "c.FullName AS customer_name,u.IsActive AS is_active,u.CreatedAt AS created_at "
                "FROM dbo.AppUsers u LEFT JOIN dbo.Customers c ON c.CustomerId=u.CustomerId ORDER BY u.Role,u.Username"
            )
            names = [column[0] for column in cursor.description]
            result = [dict(zip(names, row)) for row in cursor.fetchall()]
            cursor.close()
            return result

    def set_user_active(self, user_id: int, active: bool) -> bool:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT Role FROM dbo.AppUsers WITH (UPDLOCK,HOLDLOCK) WHERE UserId=?", user_id)
            user = cursor.fetchone()
            if not user:
                cursor.close()
                return False
            if not active and user[0] == "ADMIN":
                cursor.execute("SELECT COUNT(*) FROM dbo.AppUsers WITH (UPDLOCK,HOLDLOCK) WHERE Role='ADMIN' AND IsActive=1")
                if cursor.fetchone()[0] <= 1:
                    connection.rollback()
                    cursor.close()
                    raise ValueError("The last active administrator cannot be deactivated")
            cursor.execute("UPDATE dbo.AppUsers SET IsActive=?,UpdatedAt=SYSUTCDATETIME() WHERE UserId=?", active, user_id)
            changed = cursor.rowcount > 0
            if changed and not active:
                cursor.execute("UPDATE dbo.AppSessions SET RevokedAt=SYSUTCDATETIME() WHERE UserId=? AND RevokedAt IS NULL", user_id)
            connection.commit()
            cursor.close()
            return changed

    def update_password(self, user_id: int, salt: str, password_hash: str) -> None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE dbo.AppUsers SET PasswordSalt=?,PasswordHash=?,FailedLoginCount=0,LockedUntil=NULL,"
                "UpdatedAt=SYSUTCDATETIME() WHERE UserId=?", salt, password_hash, user_id,
            )
            if cursor.rowcount == 0:
                connection.rollback()
                raise LookupError("User account not found")
            cursor.execute("UPDATE dbo.AppSessions SET RevokedAt=SYSUTCDATETIME() WHERE UserId=? AND RevokedAt IS NULL",
                           user_id)
            connection.commit()
            cursor.close()
