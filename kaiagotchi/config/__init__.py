"""
Configuration management for Kaiagotchi.

Two loaders exist and are intentionally distinct:

* :func:`kaiagotchi.config.config.load_config` — the canonical loader used at
  startup. Merges ``defaults.toml`` with an optional system config.
* :func:`kaiagotchi.config.manager.load_config` — a hardened loader that also
  validates structure and enforces secure file permissions.

Import from the submodule you need rather than relying on package-level names.
"""

from .config import CONFIG, load_config, reload

__all__ = ["load_config", "reload", "CONFIG"]
