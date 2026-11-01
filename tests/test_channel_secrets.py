from app.application.services.channel_dashboard import ChannelService
from app.domain.entities import ApiKeyEntity, ChannelApiKeyEntity, ChannelEntity
from app.types.models import ApiKeyDTO, ChannelApiKeyDTO, ChannelDTO


class FakeRepository:
    def __init__(self):
        self.channel = ChannelEntity(id="channel-1", name="provider", api_key="provider-secret-123456", api_keys=[ChannelApiKeyEntity(id="up-1", channel_id="channel-1", name="secondary", api_key="upstream-secret-123456")])
        self.api_key = ApiKeyEntity(id="key-1", name="client", key="sk-waliapi-secret-123456")
        self.updated_channel = None
        self.updated_api_key = None

    def get_all_channels(self):
        return [self.channel]

    def get_channel(self, _channel_id):
        return self.channel

    def get_all_api_keys(self):
        return [self.api_key]

    def get_api_key(self, _key_id):
        return self.api_key

    def update_channel(self, entity):
        self.updated_channel = entity
        return True

    def update_api_key(self, entity):
        self.updated_api_key = entity
        return True

    def create_channel(self, entity):
        self.channel = entity
        return entity

    def get_channel_api_keys(self, _channel_id):
        return self.channel.api_keys

    def create_channel_api_key(self, entity):
        self.channel.api_keys.append(entity)
        return entity

    def update_channel_api_key(self, entity):
        return True

    def delete_channel_api_key(self, _channel_id, _key_id):
        return True


def test_channel_credentials_are_masked_and_masked_update_preserves_secret():
    repo = FakeRepository()
    service = ChannelService(repo, None)

    channel = service.list_channels()[0]
    assert channel.api_key.startswith("prov")
    assert channel.api_key.endswith("3456")
    assert set(channel.api_key[4:-4]) == {"*"}

    service.update_channel(ChannelDTO(id="channel-1", api_key=channel.api_key))
    assert repo.updated_channel.api_key == repo.channel.api_key


def test_api_key_is_exposed_only_on_creation_and_masked_update_preserves_secret():
    repo = FakeRepository()
    service = ChannelService(repo, None)

    listed = service.list_api_keys()[0]
    assert listed.key.startswith("sk-w")
    assert listed.key.endswith("3456")
    assert set(listed.key[4:-4]) == {"*"}

    service.update_api_key(ApiKeyDTO(id="key-1", key=listed.key))
    assert repo.updated_api_key.key == repo.api_key.key


def test_clone_channel_copies_configuration_without_reusing_id():
    repo = FakeRepository()
    service = ChannelService(repo, None)
    clone = service.clone_channel("channel-1")
    assert clone.name == "provider (copy)"
    assert clone.id != "channel-1"
    assert clone.api_key.startswith("prov")


def test_channel_upstream_keys_are_masked_and_preserve_secret_on_update():
    repo = FakeRepository()
    service = ChannelService(repo, None)
    listed = service.list_channel_api_keys("channel-1")
    assert listed[0].api_key.startswith("upst")
    assert set(listed[0].api_key[4:-4]) == {"*"}
    service.update_channel_api_key("channel-1", "up-1", ChannelApiKeyDTO(id="up-1", api_key=listed[0].api_key))
    assert repo.channel.api_keys[0].api_key == "upstream-secret-123456"


def test_channel_export_omits_secrets_by_default_and_can_include_them_explicitly():
    service = ChannelService(FakeRepository(), None)

    safe = service.export_channels()
    assert safe["secret_fields_included"] is False
    assert "api_key" not in safe["channels"][0]
    assert "api_keys" not in safe["channels"][0]

    full = service.export_channels(include_secrets=True)
    assert full["secret_fields_included"] is True
    assert full["channels"][0]["api_key"] == "provider-secret-123456"
    assert full["channels"][0]["api_keys"][0]["api_key"] == "upstream-secret-123456"


def test_channel_import_preserves_existing_secret_when_snapshot_is_redacted():
    repo = FakeRepository()
    service = ChannelService(repo, None)

    result = service.import_channels(
        [ChannelDTO(id="channel-1", name="renamed", api_key=None)],
        replace_existing=True,
    )

    assert result == {"created": [], "updated": ["channel-1"], "skipped": []}
    assert repo.updated_channel.api_key == "provider-secret-123456"
    assert repo.updated_channel.name == "renamed"


def test_channel_import_skips_existing_without_replace_flag():
    repo = FakeRepository()
    service = ChannelService(repo, None)

    result = service.import_channels([ChannelDTO(id="channel-1", name="ignored")])

    assert result == {"created": [], "updated": [], "skipped": ["channel-1"]}


def test_redacted_import_creates_disabled_channel_without_treating_mask_as_secret():
    repo = FakeRepository()
    repo.get_channel = lambda channel_id: repo.channel if channel_id == "channel-1" else None
    service = ChannelService(repo, None)

    result = service.import_channels([ChannelDTO(id="new-channel", name="redacted", api_key="prov********3456")])

    assert result["created"] == [repo.channel.id]
    assert repo.channel.api_key is None
    assert repo.channel.status == 0
