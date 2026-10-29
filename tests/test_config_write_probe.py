from kaiagotchi.core.utils import validate_config


def test_config_writeability_probe_does_not_touch_predictable_user_file(tmp_path):
    base_dir = tmp_path / "state"
    base_dir.mkdir()
    sentinel = base_dir / ".write_test"
    sentinel.write_text("user data", encoding="utf-8")

    validate_config({
        "main": {"base_dir": str(base_dir)},
        "log": {"level": "INFO"},
    })

    assert sentinel.read_text(encoding="utf-8") == "user data"
    assert list(base_dir.glob(".kaiagotchi-write-probe-*")) == []


def test_config_writeability_probe_leaves_no_temporary_file(tmp_path):
    base_dir = tmp_path / "state"
    validate_config({
        "main": {"base_dir": str(base_dir)},
        "log": {"level": "INFO"},
    })

    assert base_dir.exists()
    assert not (base_dir / ".write_test").exists()
    assert list(base_dir.iterdir()) == []
