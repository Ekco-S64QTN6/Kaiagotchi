from kaiagotchi.ai.reward import RewardEngine


def test_inventory_discoveries_are_counted_once_without_double_counting_chatter():
    engine = RewardEngine({})
    state = {
        "aps_list": [{"bssid": "aa:bb:cc:dd:ee:01"}],
        "stations_list": [{"station_mac": "11:22:33:44:55:66"}],
        "recent_captures": [
            {"timestamp": "12:00:00", "message": "New network detected: aa:bb:cc:dd:ee:01"},
            {"timestamp": "12:00:00", "message": "New station detected: 11:22:33:44:55:66"},
        ],
    }

    assert engine._extract_new_discoveries(state) == (1, 1)
    # Both identities and their chatter entries persist in later epoch snapshots,
    # but they must not generate another discovery reward.
    assert engine._extract_new_discoveries(state) == (0, 0)


def test_legacy_discovery_events_are_deduplicated_when_inventory_is_missing():
    engine = RewardEngine({})
    state = {
        "recent_captures": [
            {"timestamp": "12:00:00", "message": "New network detected: aa:bb:cc:dd:ee:01"},
            {"timestamp": "12:00:01", "message": "New station detected: 11:22:33:44:55:66"},
        ]
    }

    assert engine._extract_new_discoveries(state) == (1, 1)
    assert engine._extract_new_discoveries(state) == (0, 0)


def test_discovery_tracking_normalizes_identity_case_and_can_reset():
    engine = RewardEngine({})
    state = {
        "aps_list": [{"bssid": "aa:bb:cc:dd:ee:01"}],
        "stations_list": [{"mac": "11:22:33:44:55:66"}],
    }
    assert engine._extract_new_discoveries(state) == (1, 1)

    changed_case = {
        "aps_list": [{"bssid": "AA:BB:CC:DD:EE:01"}],
        "stations_list": [{"station_mac": "11:22:33:44:55:66"}],
    }
    assert engine._extract_new_discoveries(changed_case) == (0, 0)

    engine.reset_discoveries()
    assert engine._extract_new_discoveries(changed_case) == (1, 1)



def test_malformed_inventory_identities_are_ignored_without_hiding_valid_records():
    engine = RewardEngine({})
    state = {
        "aps_list": [
            None,
            {"bssid": ""},
            {"bssid": "   "},
            {"bssid": "not-a-mac"},
            {"bssid": "aa:bb:cc:dd:ee:01"},
        ],
        "stations_list": [
            None,
            "not-a-record",
            {"station_mac": "invalid"},
            {"station_mac": "00:11:22:33:44:55:66"},
            {"mac": "11-22-33-44-55-66"},
        ],
    }

    assert engine._extract_new_discoveries(state) == (1, 1)
    assert engine._extract_new_discoveries(state) == (0, 0)


def test_malformed_mapping_inventory_falls_back_to_a_valid_ap_key():
    engine = RewardEngine({})
    state = {
        "network": {
            "access_points": {
                "malformed-key": {"bssid": "not-a-mac"},
                "AA:BB:CC:DD:EE:02": {},
                "00:11:22:33:44:55:66": {"bssid": None},
            }
        }
    }

    assert engine._extract_new_discoveries(state) == (1, 0)
    assert engine._extract_new_discoveries(state) == (0, 0)


def test_non_string_legacy_discovery_messages_are_ignored():
    engine = RewardEngine({})
    state = {
        "recent_captures": [
            {"message": ["New network detected: aa:bb:cc:dd:ee:01"]},
            {"message": 123, "text": {"new station": "11:22:33:44:55:66"}},
            None,
            {"message": "New network detected: aa:bb:cc:dd:ee:02"},
            "New station detected: 11:22:33:44:55:66",
        ]
    }

    assert engine._extract_new_discoveries(state) == (1, 1)
    assert engine._extract_new_discoveries(state) == (0, 0)
