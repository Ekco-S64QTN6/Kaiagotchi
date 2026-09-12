"""Unit tests for core logic: reward, epoch, config, persistence, plugin dispatch.

These cover the areas the code review flagged as untested and lock in several
regressions that were fixed during the refactor.
"""

import kaiagotchi
import kaiagotchi.plugins as plugins
from kaiagotchi.ai.epoch import Epoch, EpochTracker
from kaiagotchi.ai.reward import RewardEngine
from kaiagotchi.config.config import _deep_merge
from kaiagotchi.plugins.base import Plugin
from kaiagotchi.plugins.manager import PluginManager
from kaiagotchi.storage.persistent_mood import PersistentMood
from kaiagotchi.storage.persistent_network import PersistentNetwork


# --------------------------------------------------------------------------- #
# RewardEngine
# --------------------------------------------------------------------------- #
def test_reward_engine_returns_bounded_float():
    engine = RewardEngine({})
    reward = engine.evaluate({"network": {"access_points": {}}, "metrics": {}})
    assert isinstance(reward, float)
    assert -1.0 <= reward <= 1.0


def test_reward_engine_rewards_discoveries():
    """A state with freshly discovered APs should score higher than an empty one."""
    idle = RewardEngine({}).evaluate({"network": {"access_points": {}}, "metrics": {}})
    active = RewardEngine({}).evaluate(
        {
            "network": {
                "access_points": {
                    "AA:BB:CC:00:11:22": {"essid": "net1"},
                    "AA:BB:CC:00:11:33": {"essid": "net2"},
                }
            },
            "metrics": {},
        }
    )
    assert active > idle


# --------------------------------------------------------------------------- #
# Epoch
# --------------------------------------------------------------------------- #
def test_epoch_tracker_is_epoch_alias():
    """Regression: EpochTracker must resolve to Epoch via every import path."""
    assert EpochTracker is Epoch
    assert kaiagotchi.EpochTracker is Epoch


def test_epoch_next_advances(tmp_path):
    epoch = Epoch({})
    epoch.set_reward_engine(RewardEngine({}))
    epoch.set_persistent_mood(PersistentMood(storage_dir=str(tmp_path)))

    start = epoch.epoch
    epoch.next()
    assert epoch.epoch == start + 1
    assert epoch.get_summary()["epoch"] == start + 1


def test_epoch_next_without_dependencies_is_safe():
    """next() must not raise if RewardEngine/PersistentMood were never set."""
    epoch = Epoch({})
    epoch.next()  # should log and return, not crash
    assert epoch.epoch == 0


# --------------------------------------------------------------------------- #
# Config merge
# --------------------------------------------------------------------------- #
def test_deep_merge_nested_override():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 20, "z": 30}, "b": 2}
    merged = _deep_merge(base, override)
    assert merged["a"] == 1
    assert merged["b"] == 2
    assert merged["nested"] == {"x": 1, "y": 20, "z": 30}


# --------------------------------------------------------------------------- #
# Persistence round-trips
# --------------------------------------------------------------------------- #
def test_persistent_mood_roundtrip(tmp_path):
    pm = PersistentMood(storage_dir=str(tmp_path))
    pm._min_mood_duration = 0.0  # disable the anti-flicker debounce for the test
    assert pm.set_and_save("happy", reward=0.5)

    reloaded = PersistentMood(storage_dir=str(tmp_path))
    assert reloaded.get_state()["mood"] == "happy"
    assert reloaded.get_last_reward() == 0.5
    assert reloaded.get_last_mood() == "happy"


def test_persistent_network_roundtrip(tmp_path):
    net = PersistentNetwork(storage_dir=str(tmp_path))
    net.update_bssid(
        "aa:bb:cc:dd:ee:ff",
        essid="TestNet",
        packets=10,
        beacons=5,
        channel="6",
        encryption="WPA2",
    )
    assert net.save()

    reloaded = PersistentNetwork(storage_dir=str(tmp_path))
    history = reloaded.get_bssid_history("AA:BB:CC:DD:EE:FF")
    assert history is not None
    assert history["essid"] == "TestNet"
    assert history["channel"] == "6"
    assert history["encryption"] == "WPA2"


# --------------------------------------------------------------------------- #
# Plugin dispatch wiring (regression: set_manager was never called)
# --------------------------------------------------------------------------- #
def test_plugins_on_dispatches_to_registered_manager():
    events = []

    class Recorder(Plugin):
        def on_event(self, event_name, data=None):
            events.append((event_name, data))

    manager = PluginManager()
    manager.register_plugin(Recorder("recorder"))
    plugins.set_manager(manager)
    try:
        plugins.on("mood_change", "happy")
        assert events and events[0][0] == "mood_change"
    finally:
        plugins.set_manager(None)  # type: ignore[arg-type]
