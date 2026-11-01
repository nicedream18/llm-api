"""Dependency injection container — wires up all services."""
import logging
from functools import lru_cache

from app.application.services.access_service import AccessService
from app.application.services.admin_service import AdminService
from app.application.services.channel_dashboard import ChannelService, DashboardService
from app.application.services.kb_service import KbService
from app.application.services.kb_worker import KnowledgeTaskWorker
from app.application.services.misc_services import (
    AgentService,
    McpService,
    ProxyService,
    SecurityService,
)
from app.application.services.software_service import SoftwareService
from app.application.services.wiki_service import WikiService
from app.config import config
from app.domain.agent_service import AgentChatService
from app.domain.dispatcher import Dispatcher
from app.domain.gateway import GatewayService
from app.domain.knowledge import (
    EmbedderService,
    RagContextBuilder,
    RagService,
    RetrieverService,
    TextSplitter,
)
from app.domain.security import SecurityScanner
from app.infrastructure.database.admin_repo import AdminRepository
from app.infrastructure.repositories.access_repo import AccessRepository
from app.infrastructure.repositories.agent_repo import AgentRepository
from app.infrastructure.repositories.channel_repo import ChannelRepository
from app.infrastructure.repositories.kb_repo import KbRepository
from app.infrastructure.repositories.log_repo import LogRepository
from app.infrastructure.repositories.mcp_audit_repo import McpAuditRepository
from app.infrastructure.repositories.quota_repo import QuotaRepository
from app.infrastructure.repositories.security_repo import SecurityRepository
from app.infrastructure.repositories.software_repo import SoftwareRepository
from app.infrastructure.repositories.wiki_repo import WikiRepository

logger = logging.getLogger(__name__)


class Container:
    """Singleton container holding all wired-up service instances."""

    def __init__(self):
        # Repositories
        self.channel_repo = ChannelRepository()
        self.log_repo = LogRepository()
        self.mcp_audit_repo = McpAuditRepository()
        self.software_repo = SoftwareRepository()
        self.security_repo = SecurityRepository()
        self.kb_repo = KbRepository()
        self.agent_repo = AgentRepository()
        self.quota_repo = QuotaRepository()
        self.admin_repo = AdminRepository()
        self.admin_service = AdminService(self.admin_repo)

        # Stats repository reuses log_repo
        class StatsRepository:
            def __init__(self, log_repo):
                self._log_repo = log_repo
            def get_dashboard_stats(self):
                return self._log_repo.get_dashboard_stats()
        self.stats_repo = StatsRepository(self.log_repo)

        # Domain services
        self.dispatcher = Dispatcher(self.channel_repo)
        self.gateway = GatewayService(self.dispatcher, self.channel_repo)
        self.security_scanner = SecurityScanner()
        self.security_settings = config.security
        self.text_splitter = TextSplitter()
        self.embedder = EmbedderService(self.dispatcher, self.channel_repo)
        self.retriever = RetrieverService(self.kb_repo, self.embedder)
        self.context_builder = RagContextBuilder()
        self.rag = RagService(self.retriever, self.embedder, self.gateway, self.context_builder)
        self.agent_chat = AgentChatService(self.agent_repo, self.channel_repo, self.gateway)

        # Application services
        self.channel_service = ChannelService(self.channel_repo, self.gateway)
        self.dashboard_service = DashboardService(self.log_repo, self.stats_repo)
        self.kb_service = KbService(self.kb_repo, self.rag, self.text_splitter, self.embedder)
        self.kb_worker = KnowledgeTaskWorker(self.kb_service, self.kb_repo)
        self.security_service = SecurityService(self.security_repo)
        self.agent_service = AgentService(self.agent_repo, self.agent_chat)
        self.proxy_service = ProxyService(self.gateway, self.security_scanner, self.security_settings,
                                          self.log_repo, self.security_repo, self.quota_repo, self.channel_repo)
        self.access_service = AccessService(AccessRepository())
        self.wiki_service = WikiService(WikiRepository(), self.proxy_service)
        self.software_service = SoftwareService(self.software_repo)
        self.mcp_service = McpService(self.kb_service, self.access_service, self.wiki_service, self.mcp_audit_repo, self.software_service)


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container()
