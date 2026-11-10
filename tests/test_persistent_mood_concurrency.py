from __future__ import annotations

import os
import stat
import threading

import kaiagotchi.storage.persistent_mood as persistent_mood_module
from kaiagotchi.storage.persistent_mood import PersistentMood


def test_get_state_returns_a_detached_nested_snapshot(tmp_path):
    mood = PersistentMood(storage_dir=str(tmp_path))
    with mood._state_lock:
        mood._data["test_nested"] = {"items": [1, 2]}

    snapshot = mood.get_state()
    snapshot["test_nested"]["items"].append(3)

    assert mood.get_state()["test_nested"]["items"] == [1, 2]


def test_concurrent_saves_are_serialized_and_latest_state_finishes_last(
    tmp_path, monkeypatch
):
    mood = PersistentMood(storage_dir=str(tmp_path))
    mood.set("neutral", reward=0.1)

    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    second_write_entered = threading.Event()
    persisted_values: list[float] = []
    errors: list[BaseException] = []

    def fake_atomic_save(_filepath, payload, fmt):
        assert fmt == "json"
        value = payload["reward_points"]
        if value == 0.1:
            first_write_entered.set()
            if not release_first_write.wait(timeout=5):
                raise RuntimeError("timed out waiting to release first mood save")
        elif value == 0.2:
            second_write_entered.set()
        persisted_values.append(value)
        return True

    monkeypatch.setattr(
        persistent_mood_module, "atomically_save_data", fake_atomic_save
    )
    monkeypatch.setattr(mood, "_ensure_permissions", lambda: None)

    def save_state():
        try:
            assert mood.save()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=save_state)
    first.start()
    assert first_write_entered.wait(timeout=5)

    # State updates remain available while the first filesystem write is blocked.
    mood.set("neutral", reward=0.2)
    second = threading.Thread(target=save_state)
    second.start()
    second_reached_writer_early = second_write_entered.wait(timeout=0.2)

    release_first_write.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert not second_reached_writer_early
    assert persisted_values == [0.1, 0.2]


def test_mood_state_file_is_private_to_its_owner(tmp_path):
    mood = PersistentMood(storage_dir=str(tmp_path))

    assert mood.save()
    assert stat.S_IMODE(os.stat(mood.filepath).st_mode) == 0o600


def test_mood_permission_helper_does_not_follow_symlink_targets(tmp_path):
    target = tmp_path / "external-mood-state.json"
    target.write_text('{"external": true}', encoding="utf-8")
    target.chmod(0o644)
    link = tmp_path / "mood_state.json"
    link.symlink_to(target)

    mood = PersistentMood.__new__(PersistentMood)
    mood.filepath = str(link)
    mood._ensure_permissions()

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == '{"external": true}'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_mood_permission_helper_does_not_follow_symlink_targets(tmp_path):
    target = tmp_path / "external-mood-state.json"
    target.write_text('{"external": true}', encoding="utf-8")
    target.chmod(0o644)
    link = tmp_path / "mood_state.json"
    link.symlink_to(target)

    mood = PersistentMood.__new__(PersistentMood)
    mood.filepath = str(link)
    mood._ensure_permissions()

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == '{"external": true}'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
