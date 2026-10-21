from types import SimpleNamespace

import pytest

import kaiagotchi.cli as cli


@pytest.mark.asyncio
async def test_run_agent_resets_shutdown_event_and_handles_early_config_failure(
    monkeypatch, caplog
):
    args = SimpleNamespace(
        debug=False,
        config="missing-config.toml",
        manual=False,
        no_web=True,
        web=None,
        port=None,
        host=None,
    )
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)

    def missing_config(_path):
        raise FileNotFoundError("simulated missing config")

    monkeypatch.setattr(cli, "load_config", missing_config)
    loop = __import__("asyncio").get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)

    # A previous run may have received SIGINT/SIGTERM. This run must start fresh.
    cli._shutdown_event.set()

    with caplog.at_level("ERROR", logger="kaiagotchi.cli"):
        exit_code = await cli.run_agent()

    assert exit_code == 1
    assert not cli._shutdown_event.is_set()
    # Cleanup should not raise an UnboundLocalError for web_server when config
    # loading fails before WebServer initialization.
    assert "Error during final cleanup" not in caplog.text
