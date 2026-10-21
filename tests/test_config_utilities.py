from kaiagotchi.core.utils import merge_config, remove_whitelisted


def test_remove_whitelisted_handles_mapping_and_attribute_records():
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


def test_merge_config_does_not_mutate_or_alias_defaults():
    defaults = {
        "main": {"name": "kaiagotchi", "iface": "wlan0"},
        "plugins": {"example": {"enabled": False}},
    }
    merged = merge_config({"main": {"name": "Kaia"}}, defaults)

    assert merged["main"] == {"name": "Kaia", "iface": "wlan0"}
    merged["plugins"]["example"]["enabled"] = True
    assert defaults["plugins"]["example"]["enabled"] is False


def test_merge_config_deep_copies_user_overrides():
    user = {"plugins": {"example": {"enabled": True}}}
    merged = merge_config(user, {"plugins": {"example": {"enabled": False}}})

    merged["plugins"]["example"]["enabled"] = False
    assert user["plugins"]["example"]["enabled"] is True
