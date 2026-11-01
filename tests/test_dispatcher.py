from app.domain.dispatcher import Dispatcher
from app.domain.entities import ChannelEntity


class Repo:
    def get_enabled_channels(self):
        return [ChannelEntity(id='a', name='a', models=['m'], priority=2, weight=1), ChannelEntity(id='b', name='b', models=['m'], priority=1, weight=10)]

def test_priority_group_wins():
    result = Dispatcher(Repo()).dispatch('m')
    assert result.channel.id == 'a'
