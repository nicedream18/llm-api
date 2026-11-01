"""Runtime authentication rejects legacy stateless cookies after migration."""

import hmac

from app.application.services.auth_service import AdminAuthService, verify_password
from app.config import config
from app.types.auth import AuthContext


class DurableAdminAuth(AdminAuthService):
    def __init__(self, repository, sessions):
        super().__init__(repository)
        self.sessions = sessions

    def login(self, username, password, client_ip=None):
        self.sessions.admit_login(client_ip)

        def validate(user):
            encoded = user["password_hash"] if user else "pbkdf2_sha256$310000$MDEyMzQ1Njc4OWFiY2RlZg==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            valid = verify_password(password, encoded)
            return bool(user and user["status"] == 1 and hmac.compare_digest(username, self.username) and valid)

        return self.sessions.login(username, validate, config.auth.session_ttl_seconds)

    def verify_session(self, token):
        username = self.sessions.verify(token)
        return AuthContext("admin", username, username) if username else None
