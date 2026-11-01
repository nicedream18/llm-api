"""Default-deny resource authorization, shared by HTTP and MCP."""

from app.application.errors import ApplicationError


class AccessService:
    def __init__(self, repository):
        self.repo = repository

    def allowed_resources(self, context, resource_type, action="read"):
        if context is None:
            return frozenset()
        if context.is_admin:
            return frozenset({"*"})
        return self.repo.allowed_resources(
            context.principal_type, context.principal_id, resource_type, action
        )

    def can(self, context, resource_type, resource_id, action="read"):
        allowed = self.allowed_resources(context, resource_type, action)
        return "*" in allowed or resource_id in allowed

    def require(self, context, resource_type, resource_id, action="read"):
        if not self.can(context, resource_type, resource_id, action):
            raise ApplicationError("Resource access denied", 403, "permission_denied")
