import builtins
import json
from pathlib import Path

import tomlkit

from kaiagotchi.config.manager import load_config, mask_sensitive_config, save_config
from kaiagotchi.core.utils import (
    StatusFile,
    download_file,
    merge_config,
    remove_whitelisted,
    sanitize_config_for_logging,
    unzip,
)
from kaiagotchi.core.utils import (
    save_config as save_core_config,
)


def test_load_config_missing_relative_path_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config("nested/local-config.toml")
    assert config["main"]["name"] == "kaiagotchi"
    assert (tmp_path / "nested").is_dir()


def test_invalid_config_returns_defaults_without_recursive_reload(tmp_path):
    path = tmp_path / "invalid.toml"
    path.write_text("main = []" + chr(10), encoding="utf-8")
    config = load_config(str(path))
    assert isinstance(config["main"], dict)
    assert config["main"]["name"] == "kaiagotchi"


def test_save_config_supports_filename_without_parent_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert save_config({"main": {"name": "kaiagotchi"}}, "saved.toml")
    saved = tomlkit.parse(Path("saved.toml").read_text(encoding="utf-8"))
    assert saved["main"]["name"] == "kaiagotchi"


def test_config_redaction_is_recursive_and_does_not_mutate_input():
    source = {"main": {"name": "kaiagotchi", "api_token": "secret"}, "plugins": [{"password": "pw"}]}
    original = {"main": {"name": "kaiagotchi", "api_token": "secret"}, "plugins": [{"password": "pw"}]}

    masked = mask_sensitive_config(source)
    assert source == original
    assert masked["main"]["api_token"] == "***MASKED***"
    assert masked["plugins"][0]["password"] == "***MASKED***"

    sanitized = sanitize_config_for_logging(source)
    assert source == original
    assert sanitized["main"]["api_token"] == "***MASKED***"
    assert sanitized["plugins"][0]["password"] == "***MASKED***"



def test_download_file_handles_missing_optional_requests(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def without_requests(name, *args, **kwargs):
        if name == "requests":
            raise ImportError("requests intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_requests)
    assert not download_file("https://example.invalid/file", str(tmp_path / "file"))



def test_status_file_saves_bare_relative_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    status = StatusFile("plugin-status.json")
    status.set("state", "ready")

    assert StatusFile("plugin-status.json").get("state") == "ready"


def test_status_file_ignores_non_object_json_root(tmp_path):
    path = tmp_path / "plugin-status.json"
    path.write_text("[]", encoding="utf-8")

    status = StatusFile(str(path))
    assert status.get("state", "missing") == "missing"
    assert path.read_text(encoding="utf-8") == "[]"

    status.set("state", "ready")
    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "ready"}


def test_core_utils_save_config_supports_relative_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert save_core_config({"main": {"name": "kaiagotchi"}}, "core-config.toml")
    saved = tomlkit.parse(Path("core-config.toml").read_text(encoding="utf-8"))
    assert saved["main"]["name"] == "kaiagotchi"



def test_missing_config_returns_defaults_when_directory_creation_fails(tmp_path, monkeypatch):
    from kaiagotchi.config import manager

    target = tmp_path / "unwritable" / "config.toml"

    def fail_makedirs(*_args, **_kwargs):
        raise PermissionError("simulated read-only config root")

    monkeypatch.setattr(manager.os, "makedirs", fail_makedirs)

    config = manager.load_config(str(target))

    assert config["main"]["name"] == "kaiagotchi"






def test_whitelist_handles_mapping_and_attribute_records():
    class AccessPoint:
        def __init__(self, bssid, essid):
            self.bssid = bssid
            self.essid = essid

    keep_mapping = {"bssid": "AA:BB:CC:DD:EE:01", "essid": "keep"}
    keep_object = AccessPoint("AA:BB:CC:DD:EE:02", "guest")
    blocked_object = AccessPoint("AA:BB:CC:DD:EE:03", "known")
    blocked_mapping = {"bssid": "AA:BB:CC:DD:EE:04", "ssid": "blocked"}

    result = remove_whitelisted(
        [keep_mapping, keep_object, blocked_object, blocked_mapping],
        ["AA:BB:CC:DD:EE:03", "known", "blocked"],
    )
    assert result == [keep_mapping, keep_object]


def test_merge_config_does_not_mutate_or_alias_inputs():
    defaults = {
        "main": {"name": "kaiagotchi", "iface": "wlan0"},
        "plugins": {"example": {"enabled": False}},
    }
    user = {"plugins": {"extra": {"enabled": True}}}
    merged = merge_config(user, defaults)

    assert merged["main"] == defaults["main"]
    merged["plugins"]["example"]["enabled"] = True
    merged["plugins"]["extra"]["enabled"] = False
    assert defaults["plugins"]["example"]["enabled"] is False
    assert user["plugins"]["extra"]["enabled"] is True


def test_unzip_honors_strip_dirs(tmp_path):
    import zipfile

    archive = tmp_path / "safe.zip"
    destination = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("package/docs/readme.txt", "safe")

    assert unzip(str(archive), str(destination), strip_dirs=1)
    assert (destination / "docs" / "readme.txt").read_text(encoding="utf-8") == "safe"
    assert not (destination / "package").exists()


def test_unzip_rejects_parent_traversal_before_writing(tmp_path):
    import zipfile

    archive = tmp_path / "malicious.zip"
    destination = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "not written before validation")
        zf.writestr("../escape.txt", "escaped")

    assert not unzip(str(archive), str(destination))
    assert not (destination / "safe.txt").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_unzip_rejects_windows_paths_and_symlinks(tmp_path):
    import stat
    import zipfile

    win_archive = tmp_path / "windows.zip"
    with zipfile.ZipFile(win_archive, "w") as zf:
        zf.writestr(r"C:\Windows\outside.txt", "bad")
    assert not unzip(str(win_archive), str(tmp_path / "out-win"))

    link_archive = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("outside-link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(link_archive, "w") as zf:
        zf.writestr(link, "../../escape.txt")
    assert not unzip(str(link_archive), str(tmp_path / "out-link"))



def test_legacy_web_config_defaults_to_loopback(tmp_path):
    config = load_config(str(tmp_path / "missing-legacy-config.toml"))
    assert config["ui"]["web"]["host"] == "127.0.0.1"
