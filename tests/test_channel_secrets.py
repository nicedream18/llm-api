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
