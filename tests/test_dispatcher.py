from app.domain.dispatcher import Dispatcher
from app.domain.entities import ChannelEntity


class Repo:
    def get_enabled_channels(self):
        return [ChannelEntity(id='a', name='a', models=['m'], priority=2, weight=1), ChannelEntity(id='b', name='b', models=['m'], priority=1, weight=10)]

def test_priority_group_wins():
    result = Dispatcher(Repo()).dispatch('m')
    assert result.channel.id == 'a'


def test_provider_source_is_added_to_priority_order_and_respects_exclusions():
    class ProviderSource:
        def routing_channels(self, model):
            return [ChannelEntity(id="provider:1", name="provider:1", models=[model], priority=3, weight=1)]

    dispatcher = Dispatcher(Repo(), ProviderSource())
    result = dispatcher.candidates("m")
    assert [item.channel.id for item in result] == ["provider:1", "a", "b"]
    result = dispatcher.candidates("m", {"provider:1"})
    assert [item.channel.id for item in result] == ["a", "b"]
