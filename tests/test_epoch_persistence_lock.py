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


def test_epoch_data_returns_a_detached_snapshot():
    epoch = Epoch({})
    epoch.set_reward_engine(FakeRewardEngine())
    epoch.set_persistent_mood(LockCheckingMood(epoch))
    epoch.next()

    snapshot = epoch.data()
    snapshot["reward"] = -1.0
    snapshot["nested"] = {"values": [99]}

    assert epoch.data()["reward"] == 0.25
    assert "nested" not in epoch.data()


def test_wait_for_epoch_data_returns_detached_observation_and_reward():
    epoch = Epoch({})
    epoch.set_reward_engine(FakeRewardEngine())
    epoch.set_persistent_mood(LockCheckingMood(epoch))
    epoch.observe([{"channel": 1, "clients": []}], [])
    epoch.next()

    snapshot = epoch.wait_for_epoch_data(with_observation=True, timeout=0.1)
    original_histogram = list(epoch._observation["aps_histogram"])
    snapshot["aps_histogram"][0] = 99.0
    snapshot["reward"] = -1.0

    assert epoch._observation["aps_histogram"] == original_histogram
    assert epoch.data()["reward"] == 0.25


def test_wait_for_epoch_data_without_observation_still_returns_a_copy():
    epoch = Epoch({})
    epoch.set_reward_engine(FakeRewardEngine())
    epoch.set_persistent_mood(LockCheckingMood(epoch))
    epoch.next()

    snapshot = epoch.wait_for_epoch_data(with_observation=False, timeout=0.1)
    snapshot["reward"] = -1.0

    assert epoch.data()["reward"] == 0.25


def test_get_summary_reads_a_coherent_scalar_snapshot():
    epoch = Epoch({})
    epoch.set_reward_engine(FakeRewardEngine())
    epoch.set_persistent_mood(LockCheckingMood(epoch))
    epoch.next()

    summary = epoch.get_summary()
    assert summary["epoch"] == 1
    assert summary["last_reward"] == 0.25


def test_update_network_state_detaches_caller_owned_inputs():
    epoch = Epoch({})
    aps = [{"bssid": "AA:BB:CC:DD:EE:FF", "clients": [{"mac": "11:22:33:44:55:66"}]}]
    stations = [{"station_mac": "11:22:33:44:55:66"}]
    captures = [{"type": "handshake", "metadata": {"packet_indices": [1, 2]}}]

    epoch.update_network_state(aps, stations, captures)
    aps[0]["clients"][0]["mac"] = "mutated"
    stations[0]["station_mac"] = "mutated"
    captures[0]["metadata"]["packet_indices"].append(3)

    assert epoch.aps_list[0]["clients"][0]["mac"] == "11:22:33:44:55:66"
    assert epoch.stations_list[0]["station_mac"] == "11:22:33:44:55:66"
    assert epoch.recent_captures[0]["metadata"]["packet_indices"] == [1, 2]
