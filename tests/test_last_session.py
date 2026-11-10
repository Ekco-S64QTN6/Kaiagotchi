"""Regression tests for LastSession's private storage boundary."""

import json
import stat

from kaiagotchi.storage.last_session import LastSession


def test_last_session_load_and_save_do_not_follow_symlinked_state_file(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    session_dir = home / ".kaiagotchi"
    session_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    external_file = tmp_path / "external-session.json"
    external_file.write_text('{"external": true}', encoding="utf-8")
    external_file.chmod(0o644)
    link = session_dir / "last_session.json"
    link.symlink_to(external_file)

    session = LastSession()
    assert session._storage_ready is True
    session.load()

    assert session.data == {}
    assert link.is_symlink()

    session.set("private", "session")
    session.save()

    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8")) == {
        "private": "session"
    }
    assert stat.S_IMODE(link.stat().st_mode) == 0o600
    assert external_file.read_text(encoding="utf-8") == '{"external": true}'
    assert stat.S_IMODE(external_file.stat().st_mode) == 0o644


def test_last_session_rejects_symlinked_storage_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    external_dir = tmp_path / "external-session-dir"
    external_dir.mkdir()
    external_dir.chmod(0o755)
    external_file = external_dir / "last_session.json"
    external_file.write_text('{"external": true}', encoding="utf-8")
    external_file.chmod(0o644)
    (home / ".kaiagotchi").symlink_to(external_dir, target_is_directory=True)

    session = LastSession()

    assert session._storage_ready is False
    session.load()
    assert session.data == {}
    session.set("private", "session")
    session.save()

    assert json.loads(external_file.read_text(encoding="utf-8")) == {
        "external": True
    }
    assert stat.S_IMODE(external_file.stat().st_mode) == 0o644
    assert stat.S_IMODE(external_dir.stat().st_mode) == 0o755
    assert not (external_dir / "private").exists()
