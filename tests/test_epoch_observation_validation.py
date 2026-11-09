from __future__ import annotations

from types import SimpleNamespace

import pytest

from kaiagotchi.ai.epoch import Epoch
from kaiagotchi.mesh import NumChannels


@pytest.mark.parametrize("channel", ["6", 6, "6.0", 6.0])
def test_observe_normalizes_string_and_integer_channel_ids(channel):
    epoch = Epoch({"personality": {"bond_encounters_factor": 2.0}})
    peer = SimpleNamespace(encounters=4, last_channel="11")

    epoch.observe(
        [{"channel": channel, "clients": [{"mac": "one"}, {"mac": "two"}]}],
        [peer],
    )

    snapshot = epoch.wait_for_epoch_data(with_observation=True, timeout=0.1)
    assert len(snapshot["aps_histogram"]) == NumChannels
    assert snapshot["aps_histogram"][5] == pytest.approx(1.0)
    assert snapshot["sta_histogram"][5] == pytest.approx(1.0)
    assert snapshot["peers_histogram"][10] == pytest.approx(1.0)
    assert epoch.tot_bond_factor == pytest.approx(2.0)
    assert epoch.avg_bond_factor == pytest.approx(2.0)


@pytest.mark.parametrize(
    "scale",
    [0, -1, True, float("nan"), float("inf"), "not-a-number", None],
)
def test_observe_falls_back_for_invalid_bond_encounter_scale(scale):
    epoch = Epoch({"personality": {"bond_encounters_factor": scale}})
    peer = SimpleNamespace(encounters=6, last_channel=1)

    epoch.observe([], [peer])

    assert epoch.tot_bond_factor == pytest.approx(6.0)
    assert epoch.avg_bond_factor == pytest.approx(6.0)


def test_observe_skips_malformed_optional_records_and_encounter_values():
    epoch = Epoch({"personality": {"bond_encounters_factor": 1.0}})
    peers = [
        None,
        SimpleNamespace(encounters="bad", last_channel="unknown"),
        SimpleNamespace(encounters=float("nan"), last_channel=float("inf")),
        SimpleNamespace(encounters=2, last_channel="3"),
    ]
    aps = [
        None,
        {"channel": "unknown", "clients": None},
        {"channel": "6", "clients": [{"mac": "one"}]},
        {"channel": True, "clients": []},
        {"channel": float("nan"), "clients": []},
    ]

    epoch.observe(aps, peers)
    snapshot = epoch.wait_for_epoch_data(with_observation=True, timeout=0.1)

    assert snapshot["aps_histogram"][5] == pytest.approx(1.0 / 4.0)
    assert snapshot["sta_histogram"][5] == pytest.approx(1.0)
    assert snapshot["peers_histogram"][2] == pytest.approx(1.0 / 3.0)
    assert epoch.num_peers == 3
    assert epoch.tot_bond_factor == pytest.approx(2.0)
    assert epoch.avg_bond_factor == pytest.approx(2.0 / 3.0)


def test_observe_rejects_non_list_inputs_without_overwriting_prior_histogram():
    epoch = Epoch({})
    epoch.observe([{"channel": 1, "clients": []}], [])
    before = list(epoch._observation["aps_histogram"])

    epoch.observe(None, [])

    assert epoch._observation["aps_histogram"] == before



def test_observe_skips_peer_properties_that_raise():
    class BrokenPeer:
        @property
        def encounters(self):
            raise RuntimeError("encounters unavailable")

        @property
        def last_channel(self):
            raise RuntimeError("channel unavailable")

    epoch = Epoch({"personality": {"bond_encounters_factor": "invalid"}})

    epoch.observe([], [BrokenPeer()])

    assert epoch.num_peers == 1
    assert epoch.tot_bond_factor == 0.0
    assert epoch.avg_bond_factor == 0.0
    assert sum(epoch._observation["peers_histogram"]) == 0.0
