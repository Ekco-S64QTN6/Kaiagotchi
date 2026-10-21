import builtins
from pathlib import Path

import tomlkit

from kaiagotchi.config.manager import load_config, mask_sensitive_config, save_config
from kaiagotchi.core.utils import (
    StatusFile,
    download_file,
    save_config as save_core_config,
    sanitize_config_for_logging,
    merge_config,
    remove_whitelisted,
    unzip,
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



def test_whitelist_filters_mappings_and_attribute_objects():
    class AccessPoint:
        def __init__(self, bssid, essid):
            self.bssid = bssid
            self.essid = essid

    keep_map = {"bssid": "AA:BB:CC:DD:EE:01", "essid": "keep"}
    keep_obj = AccessPoint("AA:BB:CC:DD:EE:02", "guest")
    blocked_obj = AccessPoint("AA:BB:CC:DD:EE:03", "known")
    blocked_map = {"bssid": "AA:BB:CC:DD:EE:04", "ssid": "blocked"}
    result = remove_whitelisted(
        [keep_map, keep_obj, blocked_obj, blocked_map],
        ["AA:BB:CC:DD:EE:03", "known", "blocked"],
    )
    assert result == [keep_map, keep_obj]


def test_merge_config_does_not_mutate_defaults_or_alias_nested_values():
    defaults = {"main": {"name": "kaiagotchi"}, "plugins": {"example": {"enabled": False}}}
    merged = merge_config({}, defaults)
    merged["plugins"]["example"]["enabled"] = True
    assert defaults["plugins"]["example"]["enabled"] is False


def test_safe_zip_extraction_honors_strip_dirs(tmp_path):
    import zipfile

    archive = tmp_path / "safe.zip"
    destination = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("package/docs/readme.txt", "safe")

    assert unzip(str(archive), str(destination), strip_dirs=1)
    assert (destination / "docs" / "readme.txt").read_text(encoding="utf-8") == "safe"
    assert not (destination / "package").exists()


def test_safe_zip_extraction_rejects_parent_traversal_before_writing(tmp_path):
    import zipfile

    archive = tmp_path / "malicious.zip"
    destination = tmp_path / "out"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "would be written only after validation")
        zf.writestr("../escape.txt", "escaped")

    assert not unzip(str(archive), str(destination))
    assert not (destination / "safe.txt").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_safe_zip_extraction_rejects_windows_paths_and_symlinks(tmp_path):
    import stat
    import zipfile

    win_archive = tmp_path / "windows.zip"
    with zipfile.ZipFile(win_archive, "w") as zf:
        zf.writestr("C:\\Windows\\outside.txt", "bad")
    assert not unzip(str(win_archive), str(tmp_path / "out-win"))

    link_archive = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("outside-link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(link_archive, "w") as zf:
        zf.writestr(link, "../../escape.txt")
    assert not unzip(str(link_archive), str(tmp_path / "out-link"))
