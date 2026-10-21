import time

from kaiagotchi.storage.persistent_mood import PersistentMood


def test_mood_throttle_preserves_reward_energy_and_curiosity(tmp_path):
    mood = PersistentMood(storage_dir=str(tmp_path))
    mood._last_mood_change = time.time()
    mood._min_mood_duration = 3.0

    assert mood.set_and_save("happy", reward=0.75, energy=0.25, curiosity=0.9)

    # Mood transition is debounced, but independent state still updates.
    assert mood.get_mood() == "neutral"
    state = mood.get_state()
    assert state["reward_points"] == 0.75
    assert state["last_reward"] == 0.75
    assert state["energy"] == 0.25
    assert state["curiosity"] == 0.9

    restored = PersistentMood(storage_dir=str(tmp_path))
    restored_state = restored.get_state()
    assert restored_state["mood"] == "neutral"
    assert restored_state["reward_points"] == 0.75
    assert restored_state["last_reward"] == 0.75


def test_mood_can_change_after_minimum_duration(tmp_path):
    mood = PersistentMood(storage_dir=str(tmp_path))
    mood._min_mood_duration = 3.0
    mood._last_mood_change = time.time() - 4.0

    mood.set("curious", reward=0.4)

    assert mood.get_mood() == "curious"
    assert mood.get_state()["reward_points"] == 0.4
