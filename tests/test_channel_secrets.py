from app.application.services.channel_dashboard import ChannelService
from app.domain.entities import ApiKeyEntity, ChannelEntity
from app.types.models import ApiKeyDTO, ChannelDTO


class FakeRepository:
    def __init__(self):
        self.channel = ChannelEntity(id="channel-1", name="provider", api_key="provider-secret-123456")
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
