from __future__ import annotations

import json
import os
import stat

from kaiagotchi.storage import file_io


def test_atomic_save_syncs_file_before_replace_and_directory_after(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def record_fsync(fd: int) -> None:
        mode = os.fstat(fd).st_mode
        events.append("directory_fsync" if stat.S_ISDIR(mode) else "file_fsync")
        real_fsync(fd)

    def record_replace(source: str, destination: str) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(file_io.os, "fsync", record_fsync)
    monkeypatch.setattr(file_io.os, "replace", record_replace)

    assert file_io.atomically_save_data(str(target), {"status": "ok"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "ok"}
    assert events == ["file_fsync", "replace", "directory_fsync"]


def test_atomic_save_preserves_existing_mode(tmp_path):
    target = tmp_path / "state.json"
    target.write_text('{"old": true}', encoding="utf-8")
    target.chmod(0o640)

    assert file_io.atomically_save_data(str(target), {"new": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_atomic_save_removes_temp_file_when_json_serialization_fails(tmp_path):
    target = tmp_path / "state.json"
    target.write_text('{"keep": true}', encoding="utf-8")

    assert file_io.atomically_save_data(
        str(target),
        {"not_json_serializable": object()},
    ) is False

    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["state.json"]


def test_atomic_save_removes_temp_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text('{"keep": true}', encoding="utf-8")

    def fail_replace(_source: str, _destination: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(file_io.os, "replace", fail_replace)

    assert file_io.atomically_save_data(str(target), {"new": True}) is False

    assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["state.json"]


def test_atomic_save_supports_relative_paths(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    monkeypatch.chdir(tmp_path)

    assert file_io.atomically_save_data("state.json", {"relative": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"relative": True}
