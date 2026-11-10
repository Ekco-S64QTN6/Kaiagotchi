from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import kaiagotchi.network.networkmanager as networkmanager


def _write_interfaces(root: Path, mapping: dict[str, str]) -> None:
    for name, mac in mapping.items():
        address = root / name / "address"
        address.parent.mkdir(parents=True)
        address.write_text(mac + "\n", encoding="ascii")


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_intended_interfaces_include_selected_default_and_extra_capture_dongles():
    config = {
        "main": {
            "iface": "wlan1",
            "capture_iface": "wlan0",
            "capture_ifaces": ["wlan3", "wlan4"],
        }
    }

    assert networkmanager.intended_capture_interfaces(config, "wlan3") == [
        "wlan3",
        "wlan4",
    ]


def test_intended_interfaces_refuse_to_reserve_the_primary_uplink():
    config = {
        "main": {
            "iface": "wlan1",
            "capture_iface": "wlan1",
        }
    }

    with pytest.raises(networkmanager.NetworkManagerReservationError, match="managed/internet"):
        networkmanager.intended_capture_interfaces(config)


def test_updated_reservation_preserves_existing_selectors_and_other_settings():
    original = (
        "[connection]\n"
        "id=unrelated\n"
        "\n"
        "[keyfile]\n"
        "path=/etc/NetworkManager/system-connections\n"
        "unmanaged-devices=interface-name:lo;mac:00:11:22:33:44:55\n"
    )

    updated = networkmanager._updated_reservation_text(
        original,
        {"aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"},
    )

    assert "[connection]\nid=unrelated" in updated
    assert "path=/etc/NetworkManager/system-connections" in updated
    assert (
        "unmanaged-devices=interface-name:lo;mac:00:11:22:33:44:55;"
        "mac:aa:bb:cc:dd:ee:01;mac:aa:bb:cc:dd:ee:02"
    ) in updated



def test_updated_reservation_combines_duplicate_device_sections():
    original = (
        "[keyfile]\n"
        "unmanaged-devices=mac:00:11:22:33:44:55\n"
        "path=/etc/NetworkManager/system-connections\n"
        "\n"
        "[connection]\n"
        "id=other\n"
        "\n"
        "[keyfile]\n"
        "unmanaged-devices=interface-name:lo\n"
    )

    updated = networkmanager._updated_reservation_text(
        original, {"aa:bb:cc:dd:ee:01"}
    )

    assert updated.count("unmanaged-devices=") == 1
    assert (
        "unmanaged-devices=mac:00:11:22:33:44:55;interface-name:lo;"
        "mac:aa:bb:cc:dd:ee:01"
    ) in updated
    assert "path=/etc/NetworkManager/system-connections" in updated
    assert "[connection]\nid=other" in updated


def test_reservation_file_is_created_reloaded_and_verified_for_every_capture_adapter(
    tmp_path, monkeypatch
):
    sysfs = tmp_path / "sys"
    _write_interfaces(
        sysfs,
        {
            "wlan0": "aa:bb:cc:dd:ee:00",
            "wlan3": "aa:bb:cc:dd:ee:03",
        },
    )
    reservation = tmp_path / "NetworkManager" / "99-ignore-project-dongle.conf"
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[0] == "nmcli":
            return _completed(stdout="GENERAL.NM-MANAGED: no\n")
        return _completed()

    monkeypatch.setattr(networkmanager, "_is_root", lambda: True)
    result = networkmanager.ensure_networkmanager_reservation(
        {
            "main": {
                "iface": "wlan1",
                "capture_iface": "wlan0",
                "capture_ifaces": ["wlan3"],
            }
        },
        reservation_path=reservation,
        sysfs_root=sysfs,
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        routes=(),
    )

    written = reservation.read_text(encoding="utf-8")
    assert "mac:aa:bb:cc:dd:ee:00" in written
    assert "mac:aa:bb:cc:dd:ee:03" in written
    assert result["reloaded"] is True
    assert [row["nm_managed"] for row in result["interfaces"]] == ["no", "no"]
    assert commands[0] == ["systemctl", "reload", "NetworkManager"]
    assert sum(command[0] == "nmcli" for command in commands) == 2


def test_non_root_startup_fails_with_exact_privileged_rerun_command(
    tmp_path, monkeypatch
):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "aa:bb:cc:dd:ee:03"})
    reservation = tmp_path / "missing.conf"
    monkeypatch.setattr(networkmanager, "_is_root", lambda: False)

    with pytest.raises(
        networkmanager.NetworkManagerReservationError,
        match=r"sudo .*kaiagotchi\.cli.*--capture-interface wlan3",
    ):
        networkmanager.ensure_networkmanager_reservation(
            {"main": {"iface": "wlan1", "capture_iface": "wlan3"}},
            reservation_path=reservation,
            sysfs_root=sysfs,
            runner=lambda *_args, **_kwargs: _completed(
                stdout="GENERAL.NM-MANAGED: no\n"
            ),
            which=lambda name: f"/usr/bin/{name}",
        routes=(),
        )

    assert not reservation.exists()


def test_managed_live_state_triggers_reload_even_when_file_already_covers_mac(
    tmp_path, monkeypatch
):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "aa:bb:cc:dd:ee:03"})
    reservation = tmp_path / "99-ignore-project-dongle.conf"
    reservation.write_text(
        "[keyfile]\nunmanaged-devices=mac:aa:bb:cc:dd:ee:03\n",
        encoding="utf-8",
    )
    nm_states = iter(["yes", "no"])
    commands = []
    monkeypatch.setattr(networkmanager, "_is_root", lambda: True)

    def runner(command, **_kwargs):
        commands.append(command)
        if command[0] == "nmcli":
            return _completed(
                stdout=f"GENERAL.NM-MANAGED: {next(nm_states)}\n"
            )
        return _completed()

    result = networkmanager.ensure_networkmanager_reservation(
        {"main": {"iface": "wlan1", "capture_iface": "wlan3"}},
        reservation_path=reservation,
        sysfs_root=sysfs,
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        routes=(),
    )

    assert result["reloaded"] is True
    assert commands == [
        ["nmcli", "-f", "GENERAL.NM-MANAGED", "device", "show", "wlan3"],
        ["systemctl", "reload", "NetworkManager"],
        ["nmcli", "-f", "GENERAL.NM-MANAGED", "device", "show", "wlan3"],
    ]


def test_live_networkmanager_managed_state_after_reload_blocks_capture(
    tmp_path, monkeypatch
):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "aa:bb:cc:dd:ee:03"})
    reservation = tmp_path / "99-ignore-project-dongle.conf"
    reservation.write_text(
        "[keyfile]\nunmanaged-devices=mac:aa:bb:cc:dd:ee:03\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(networkmanager, "_is_root", lambda: True)

    def runner(command, **_kwargs):
        if command[0] == "nmcli":
            return _completed(stdout="GENERAL.NM-MANAGED: yes\n")
        return _completed()

    with pytest.raises(networkmanager.NetworkManagerReservationError, match="still reports"):
        networkmanager.ensure_networkmanager_reservation(
            {"main": {"iface": "wlan1", "capture_iface": "wlan3"}},
            reservation_path=reservation,
            sysfs_root=sysfs,
            runner=runner,
            which=lambda name: f"/usr/bin/{name}",
        routes=(),
        )


def test_doctor_reports_adapter_state_process_parent_and_plasma_journal(
    tmp_path, monkeypatch
):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "aa:bb:cc:dd:ee:03"})
    reservation = tmp_path / "99-ignore-project-dongle.conf"
    reservation.write_text(
        "[keyfile]\nunmanaged-devices=mac:aa:bb:cc:dd:ee:03\n",
        encoding="utf-8",
    )

    proc_root = tmp_path / "proc"
    process_dir = proc_root / "4242"
    process_dir.mkdir(parents=True)
    (process_dir / "cmdline").write_bytes(
        b"/usr/sbin/airodump-ng\x00--write\x00capture\x00"
    )
    (process_dir / "stat").write_text(
        "4242 (airodump-ng) S 55 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )

    def runner(command, **_kwargs):
        if command[0] == "nmcli" and "GENERAL.NM-MANAGED" in command:
            return _completed(stdout="GENERAL.NM-MANAGED: no\n")
        if command[0] == "nmcli":
            return _completed(stdout="GENERAL.STATE: 100 (connected)\n")
        if command[0] == "iw":
            return _completed(stdout="Interface wlan3\n\ttype managed\n")
        if command[0] == "journalctl":
            return _completed(
                stdout=(
                    "Nov 10 plasmashell[123]: Wireless scan failed: "
                    "Scanning not allowed while unavailable\n"
                )
            )
        return _completed()

    monkeypatch.setattr(
        networkmanager.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    report = networkmanager.build_doctor_report(
        {"main": {"iface": "wlan1", "capture_iface": "wlan3"}},
        reservation_path=reservation,
        sysfs_root=sysfs,
        proc_root=proc_root,
        runner=runner,
    )

    adapter = report["interfaces"][0]
    assert adapter["mac"] == "aa:bb:cc:dd:ee:03"
    assert adapter["in_config"] is True
    assert adapter["nm_managed"] == "no"
    assert adapter["kernel_type"] == "managed"
    assert report["uplink"]["state"] == "100 (connected)"
    assert report["airodump_processes"] == [
        {"pid": 4242, "ppid": 55, "command": "/usr/sbin/airodump-ng --write capture"}
    ]
    assert report["journal_scan_rejections"]["count"] == 1


def test_the_reservation_is_written_where_networkmanager_reads_it():
    """NetworkManager.conf(5): unmanaged-devices is a [keyfile] key; a [device]
    section has no such key and NetworkManager would leave the dongle managed."""
    updated = networkmanager._updated_reservation_text("", {"aa:bb:cc:dd:ee:01"})
    assert updated == "[keyfile]\nunmanaged-devices=mac:aa:bb:cc:dd:ee:01\n"


def test_an_existing_hand_written_keyfile_reservation_is_recognised(tmp_path, monkeypatch):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "6c:4c:bc:e3:47:63"})
    reservation = tmp_path / "99-ignore-project-dongle.conf"
    reservation.write_text("[keyfile]\nunmanaged-devices=mac:00:d0:41:be:81:1d;mac:6c:4c:bc:e3:47:63\n")
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        return _completed(stdout="GENERAL.NM-MANAGED: no\n")

    monkeypatch.setattr(networkmanager, "_is_root", lambda: True)
    result = networkmanager.ensure_networkmanager_reservation(
        {"main": {"iface": "wlan0", "capture_iface": "wlan3"}},
        reservation_path=reservation, sysfs_root=sysfs, runner=runner,
        which=lambda name: f"/usr/bin/{name}", routes=(),
    )
    assert result["reloaded"] is False
    assert ["systemctl", "reload", "NetworkManager"] not in commands
    assert reservation.read_text().count("unmanaged-devices=") == 1


def test_an_interface_carrying_the_default_route_is_never_reserved(tmp_path, monkeypatch):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan0": "3c:0a:f3:32:13:05"})
    route = tmp_path / "route"
    route.write_text(
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
        "wlan0\t00000000\tFE01A8C0\t0003\t0\t0\t600\t00000000\n"
    )
    reservation = tmp_path / "99-ignore-project-dongle.conf"
    monkeypatch.setattr(networkmanager, "_is_root", lambda: True)
    with pytest.raises(networkmanager.NetworkManagerReservationError, match="default route"):
        networkmanager.ensure_networkmanager_reservation(
            {"main": {"capture_iface": "wlan0"}},          # no [main].iface to compare against
            reservation_path=reservation, sysfs_root=sysfs,
            runner=lambda *a, **k: _completed(stdout="GENERAL.NM-MANAGED: yes\n"),
            which=lambda name: f"/usr/bin/{name}", routes=(route,),
        )
    assert not reservation.exists()


def test_a_changed_mac_reserves_the_permanent_address(tmp_path):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "02:11:22:33:44:55"})
    (sysfs / "wlan3" / "addr_assign_type").write_text("3\n")
    seen = []

    def runner(command, **_kwargs):
        seen.append(command)
        return _completed(stdout="Permanent address: 6c:4c:bc:e3:47:63\n")

    assert networkmanager.read_interface_mac("wlan3", sysfs_root=sysfs, runner=runner) == "6c:4c:bc:e3:47:63"
    assert seen == [["ethtool", "-P", "wlan3"]]


def test_a_changed_mac_without_a_readable_permanent_one_fails_closed(tmp_path):
    sysfs = tmp_path / "sys"
    _write_interfaces(sysfs, {"wlan3": "02:11:22:33:44:55"})
    (sysfs / "wlan3" / "addr_assign_type").write_text("3\n")
    with pytest.raises(networkmanager.NetworkManagerReservationError, match="permanent"):
        networkmanager.read_interface_mac("wlan3", sysfs_root=sysfs, runner=lambda *a, **k: _completed(1))
