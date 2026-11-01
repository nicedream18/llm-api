"""Admin login/session application service."""
from __future__ import annotations

from app.application.services.auth_service import (
    AdminAuthService,
    AuthError,
    hash_password,
)
from app.infrastructure.database.admin_repo import AdminRepository
from app.infrastructure.repositories.admin_session_repo import AdminSessionRepository


class AdminService:
    def __init__(self, repository: AdminRepository | None = None, sessions=None):
        self.repo = repository or AdminRepository()
        self.sessions = sessions or (AdminSessionRepository() if isinstance(self.repo, AdminRepository) else None)
        self.auth: AdminAuthService
        if self.sessions:
            from app.application.services.admin_sessions import DurableAdminAuth
            self.auth = DurableAdminAuth(self.repo, self.sessions)
        else:
            self.auth = AdminAuthService(self.repo)

    def logout(self, token):
        if self.sessions:
            self.sessions.revoke_token(token)

    def login(self, username: str, password: str, client_ip: str | None, request_id: str | None) -> str:
        try:
            token = self.auth.login(username, password, client_ip)
            self.repo.write_audit(username, "login", request_id, client_ip, True)
            return token
        except AuthError:
            self.repo.write_audit(username, "login", request_id, client_ip, False)
            raise

    def change_password(self, username: str, password: str, request_id: str | None, client_ip: str | None) -> None:
        if len(password) < 12:
            raise AuthError("Password must contain at least 12 characters", 422, "validation_error")
        if not self.repo.change_password(username, hash_password(password)):
            raise AuthError("Admin account not found", 404, "not_found")
        self.repo.write_audit(username, "change_password", request_id, client_ip, True)

    def audit(self, username: str | None, action: str, request_id: str | None, client_ip: str | None) -> None:
        self.repo.write_audit(username, action, request_id, client_ip, True)
