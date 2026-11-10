"""Contract tests for the legacy Bettercap import-compatibility shims."""

import pytest

from kaiagotchi.network.integrations.bettercap import BettercapIntegration, Client


@pytest.mark.parametrize("factory", [BettercapIntegration, Client])
def test_legacy_bettercap_start_fails_explicitly(factory):
    instance = factory({})

    with pytest.raises(NotImplementedError, match="Bettercap backend is not supported"):
        instance.start()


@pytest.mark.parametrize("factory", [BettercapIntegration, Client])
def test_legacy_bettercap_stop_is_safe_without_a_started_process(factory):
    instance = factory({})

    # start() cannot acquire a process, so stop is an idempotent no-op.
    assert instance.stop() is None
    assert instance.stop() is None
