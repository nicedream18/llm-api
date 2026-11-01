def test_container_wires_shared_services_to_expected_dependencies(monkeypatch):
    import app.container as container_module

    class Factory:
        def __init__(self, *args):
            self.args = args

    factory_names = (
        "ChannelRepository", "LogRepository", "McpAuditRepository", "SoftwareRepository",
        "ProviderRepository", "PlatformRepository", "SecurityRepository", "KbRepository",
        "AgentRepository", "QuotaRepository", "AdminRepository", "AdminService",
        "Dispatcher", "GatewayService", "SecurityScanner", "TextSplitter", "EmbedderService",
        "IndexService", "RetrieverService", "RagContextBuilder", "RagService", "AgentChatService",
        "ChannelService", "DashboardService", "KbService", "KnowledgeTaskWorker",
        "SecurityService", "AgentService", "ProxyService", "AccessRepository", "AccessService",
        "WikiRepository", "WikiService", "SoftwareService", "ProviderService", "PlatformService",
        "McpService", "ProviderSyncWorker", "RoutingRepository",
    )
    for name in factory_names:
        monkeypatch.setattr(container_module, name, Factory)

    container = container_module.Container()
    assert container.gateway.args == (container.dispatcher, container.channel_repo, container.routing_repo)
    assert container.embedder.args == (container.dispatcher, container.channel_repo)
    assert container.retriever.args == (container.kb_repo, container.embedder, container.index_service)
    assert container.rag.args == (
        container.retriever, container.embedder, container.gateway, container.context_builder,
    )
    assert container.kb_worker.args == (container.kb_service, container.kb_repo)
    assert container.proxy_service.args == (
        container.gateway, container.security_scanner, container.security_settings,
        container.log_repo, container.security_repo, container.quota_repo, container.channel_repo,
    )
    assert container.wiki_service.args == (container.wiki_service.args[0], container.proxy_service)
    assert container.mcp_service.args[-1] == container.software_service


def test_get_container_returns_one_cached_container(monkeypatch):
    import app.container as container_module

    container_module.get_container.cache_clear()
    created = []

    class FakeContainer:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr(container_module, "Container", FakeContainer)
    try:
        first = container_module.get_container()
        second = container_module.get_container()
        assert first is second
        assert len(created) == 1
    finally:
        container_module.get_container.cache_clear()
