import logging

import pytest

from kaiagotchi.ui.web.server import _log_listener_started


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "[::]", ""])
def test_wildcard_bind_warns_that_telemetry_has_no_authentication(host, caplog):
    with caplog.at_level(logging.WARNING, logger="kaiagotchi.ui.web.server"):
        _log_listener_started(host, 8080)

    assert "all network interfaces" in caplog.text
    assert "no authentication" in caplog.text
    assert "localhost" not in caplog.text


def test_loopback_bind_logs_a_usable_url_without_exposure_warning(caplog):
    with caplog.at_level(logging.INFO, logger="kaiagotchi.ui.web.server"):
        _log_listener_started("127.0.0.1", 8080)

    assert "http://127.0.0.1:8080" in caplog.text
    assert "no authentication" not in caplog.text


def test_ipv6_loopback_url_is_bracketed(caplog):
    with caplog.at_level(logging.INFO, logger="kaiagotchi.ui.web.server"):
        _log_listener_started("::1", 8080)

    assert "http://[::1]:8080" in caplog.text
