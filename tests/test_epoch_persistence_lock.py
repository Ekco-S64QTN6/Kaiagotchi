from kaiagotchi.ai.epoch import Epoch


class FakeRewardEngine:
    def evaluate(self, _state):
        return 0.25


class LockCheckingMood:
    def __init__(self, epoch):
        self.epoch = epoch
        self.calls = []

    def apply_reward(self, reward, epoch_data=None):
        # PersistentMood writes synchronously; it must not block the shared
        # epoch state lock used by track()/update_network_state().
        assert not self.epoch._lock.locked()
        self.calls.append((reward, dict(epoch_data or {})))


def test_epoch_persists_reward_after_releasing_shared_state_lock():
    epoch = Epoch({})
    mood = LockCheckingMood(epoch)
    epoch.set_reward_engine(FakeRewardEngine())
    epoch.set_persistent_mood(mood)

    epoch.next()

    assert len(mood.calls) == 1
    reward, snapshot = mood.calls[0]
    assert reward == 0.25
    assert snapshot["reward"] == 0.25
    assert snapshot["epoch"] == 0
    assert epoch._epoch_data_ready.is_set()
    assert epoch.epoch == 1
