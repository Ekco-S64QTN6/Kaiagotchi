import builtins
from pathlib import Path

import tomlkit

from kaiagotchi.config.manager import load_config, mask_sensitive_config, save_config
from kaiagotchi.core.utils import download_file, sanitize_config_for_logging


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
