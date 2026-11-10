"""Durable NetworkManager reservation and operator diagnostics.

Capture adapters are reserved by a NetworkManager drop-in, not by transient
nmcli device set mutations. The reservation survives normal shutdowns and
process crashes; only the Linux wireless interface type is restored at teardown.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

RESERVATION_PATH = Path("/etc/NetworkManager/conf.d/99-ignore-project-dongle.conf")
SYS_CLASS_NET = Path("/sys/class/net")
PROC_ROOT = Path("/proc")
_MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_SCAN_REJECTION = "Scanning not allowed while unavailable"


class NetworkManagerReservationError(RuntimeError):
    """Raised when NetworkManager could still contend for a capture adapter."""


def intended_capture_interfaces(
    config: dict[str, Any] | None,
    active_interface: str | None = None,
) -> list[str]:
    """Return every configured capture dongle, with the active one first.

    main.capture_iface remains the selected capture interface. The optional
    main.capture_ifaces list adds other dedicated dongles that must also stay
    unmanaged even when they are not selected for the current session.
    """
    cfg = config if isinstance(config, dict) else {}
    main = cfg.get("main")
    main = main if isinstance(main, dict) else {}

    selected = (
        active_interface
        or os.environ.get("KAIAGOTCHI_INTERFACE")
        or main.get("capture_iface")
        or cfg.get("interface")
        or "wlan1"
    )
    candidates: list[Any] = [selected]
    extras = main.get("capture_ifaces", [])
    if isinstance(extras, str):
        candidates.append(extras)
    elif isinstance(extras, (list, tuple, set)):
        candidates.extend(extras)

    uplink = main.get("iface")
    result: list[str] = []
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        if not isinstance(candidate, str) or not _INTERFACE_RE.fullmatch(candidate):
            raise NetworkManagerReservationError(
                f"Invalid capture interface name in configuration: {candidate!r}"
            )
        if uplink and candidate == uplink:
            raise NetworkManagerReservationError(
                f"Refusing to reserve {candidate!r}: [main].iface identifies the "
                "managed/internet adapter. Select a dedicated capture dongle instead."
            )
        if candidate not in result:
            result.append(candidate)
    return result


def read_interface_mac(
    interface: str,
    *,
    sysfs_root: Path = SYS_CLASS_NET,
) -> str:
    """Resolve and validate an interface's sysfs MAC address."""
    if not _INTERFACE_RE.fullmatch(interface):
        raise NetworkManagerReservationError(
            f"Invalid capture interface name: {interface!r}"
        )
    address_path = sysfs_root / interface / "address"
    try:
        mac = address_path.read_text(encoding="ascii").strip().lower()
    except OSError as exc:
        raise NetworkManagerReservationError(
            f"Cannot read the MAC address for capture interface {interface!r} "
            f"from {address_path}: {exc}. Connect the adapter and verify its name."
        ) from exc
    if not _MAC_RE.fullmatch(mac) or mac == "00:00:00:00:00:00":
        raise NetworkManagerReservationError(
            f"Interface {interface!r} returned an invalid MAC address: {mac!r}"
        )
    return mac


def parse_unmanaged_devices(content: str) -> list[str]:
    """Read all unmanaged-devices selectors from [device] sections."""
    section = ""
    entries: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section != "device" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().lower() == "unmanaged-devices":
            value = value.split("#", 1)[0]
            entries.extend(item.strip() for item in value.split(";") if item.strip())
    return entries


def _updated_reservation_text(content: str, intended_macs: Iterable[str]) -> str:
    """Merge MAC selectors into the app-owned drop-in without dropping others."""
    entries = parse_unmanaged_devices(content)
    seen = {entry.lower() for entry in entries}
    for mac in intended_macs:
        selector = f"mac:{mac.lower()}"
        if selector not in seen:
            entries.append(selector)
            seen.add(selector)

    rendered = ";".join(entries)
    lines = content.splitlines()
    section = ""
    first_device_header: int | None = None
    key_indices: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            if section == "device" and first_device_header is None:
                first_device_header = index
            continue
        if section == "device" and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().lower()
            if key == "unmanaged-devices":
                key_indices.append(index)

    if first_device_header is not None:
        if key_indices:
            lines[key_indices[0]] = f"unmanaged-devices={rendered}"
            for index in reversed(key_indices[1:]):
                del lines[index]
        else:
            lines.insert(first_device_header + 1, f"unmanaged-devices={rendered}")
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(("[device]", f"unmanaged-devices={rendered}"))

    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    """Atomically replace the NetworkManager drop-in with root-readable config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise NetworkManagerReservationError(
            f"Refusing to replace symlinked NetworkManager config: {path}"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _command_output(
    command: list[str],
    *,
    runner: Callable[..., Any] = subprocess.run,
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise NetworkManagerReservationError(
            f"Required command not found: {command[0]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NetworkManagerReservationError(
            f"Command {' '.join(command)!r} timed out after {timeout:g}s"
        ) from exc
    return (
        int(getattr(result, "returncode", 1)),
        str(getattr(result, "stdout", "") or ""),
        str(getattr(result, "stderr", "") or ""),
    )


def _field_value(output: str, field: str) -> str | None:
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().upper() == field.upper():
            return value.strip()
    return None


def _is_root() -> bool:
    get_euid = getattr(os, "geteuid", None)
    return bool(get_euid and get_euid() == 0)


def _root_rerun_command(interface: str) -> str:
    """Build a privileged rerun that preserves config and interface selection."""
    command = [sys.executable, "-m", "kaiagotchi.cli", *sys.argv[1:]]
    if not any(item in ("--interface", "--capture-interface") for item in command):
        command.extend(("--capture-interface", interface))

    environment = []
    for name in ("KAIA_CONFIG", "KAIAGOTCHI_INTERFACE"):
        value = os.environ.get(name)
        if value:
            environment.extend((f"{name}={value}",))
    return "sudo " + shlex.join(["env", *environment, *command])


def _reload_networkmanager(
    *,
    runner: Callable[..., Any],
) -> None:
    if not _is_root():
        raise NetworkManagerReservationError(
            "NetworkManager must reload the durable capture reservation. Run "
            "sudo systemctl reload NetworkManager, then restart Kaiagotchi."
        )
    code, _stdout, stderr = _command_output(
        ["systemctl", "reload", "NetworkManager"], runner=runner
    )
    if code:
        detail = stderr.strip() or f"exit code {code}"
        raise NetworkManagerReservationError(
            "Could not reload NetworkManager after updating the capture reservation: "
            f"{detail}. Run sudo systemctl reload NetworkManager and retry."
        )


def ensure_networkmanager_reservation(
    config: dict[str, Any] | None,
    active_interface: str | None = None,
    *,
    reservation_path: Path = RESERVATION_PATH,
    sysfs_root: Path = SYS_CLASS_NET,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Create/repair the permanent reservation and verify live NM state.

    NetworkManager is optional on systems that do not install nmcli. When
    present, failure to reserve or verify any intended adapter blocks capture.
    """
    if not which("nmcli"):
        return {
            "available": False,
            "interfaces": [],
            "reservation_path": str(reservation_path),
            "reloaded": False,
        }

    interfaces = intended_capture_interfaces(config, active_interface)
    interface_macs = {
        interface: read_interface_mac(interface, sysfs_root=sysfs_root)
        for interface in interfaces
    }
    intended_macs = set(interface_macs.values())

    if reservation_path.is_symlink():
        raise NetworkManagerReservationError(
            f"Refusing to follow symlinked NetworkManager config: {reservation_path}"
        )
    try:
        original = reservation_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    except OSError as exc:
        raise NetworkManagerReservationError(
            f"Cannot read NetworkManager reservation {reservation_path}: {exc}"
        ) from exc

    existing_entries = parse_unmanaged_devices(original)
    existing_macs = {
        entry[4:].strip().lower()
        for entry in existing_entries
        if entry.lower().startswith("mac:")
    }
    changed = not intended_macs.issubset(existing_macs)
    reloaded = False

    if changed:
        if not _is_root():
            command = _root_rerun_command(active_interface or interfaces[0])
            raise NetworkManagerReservationError(
                "The permanent NetworkManager capture reservation is missing or "
                f"incomplete at {reservation_path}. Kaiagotchi will not start recon "
                "while NetworkManager may contend for a capture adapter.\n"
                "Run this exact command once to create the reservation and retry:\n"
                f"  {command}"
            )
        updated = _updated_reservation_text(original, intended_macs)
        try:
            _atomic_write(reservation_path, updated)
        except OSError as exc:
            raise NetworkManagerReservationError(
                f"Could not write {reservation_path}: {exc}"
            ) from exc
        _reload_networkmanager(runner=runner)
        reloaded = True

    statuses: dict[str, str] = {}
    for interface in interfaces:
        code, stdout, stderr = _command_output(
            [
                "nmcli",
                "-f",
                "GENERAL.NM-MANAGED",
                "device",
                "show",
                interface,
            ],
            runner=runner,
        )
        if code:
            detail = stderr.strip() or f"exit code {code}"
            raise NetworkManagerReservationError(
                f"Could not verify NetworkManager state for {interface}: {detail}"
            )
        value = _field_value(stdout, "GENERAL.NM-MANAGED")
        if value is None:
            raise NetworkManagerReservationError(
                f"nmcli did not report GENERAL.NM-MANAGED for {interface}; "
                "refusing to start recon without a verified reservation."
            )
        statuses[interface] = value.lower()

    if any(value != "no" for value in statuses.values()) and not reloaded:
        _reload_networkmanager(runner=runner)
        reloaded = True
        statuses.clear()
        for interface in interfaces:
            code, stdout, stderr = _command_output(
                [
                    "nmcli",
                    "-f",
                    "GENERAL.NM-MANAGED",
                    "device",
                    "show",
                    interface,
                ],
                runner=runner,
            )
            value = _field_value(stdout, "GENERAL.NM-MANAGED") if code == 0 else None
            if value is None:
                detail = stderr.strip() or f"exit code {code}"
                raise NetworkManagerReservationError(
                    f"Could not verify NetworkManager state for {interface} "
                    f"after reload: {detail}"
                )
            statuses[interface] = value.lower()

    managed = [name for name, value in statuses.items() if value != "no"]
    if managed:
        raise NetworkManagerReservationError(
            "NetworkManager still reports these dedicated capture adapters as "
            f"managed: {', '.join(managed)}. Kaiagotchi refuses to start recon. "
            "Check that the MAC reservation matches the current adapters, then run "
            "sudo systemctl reload NetworkManager."
        )

    return {
        "available": True,
        "interfaces": [
            {"name": name, "mac": mac, "nm_managed": statuses[name]}
            for name, mac in interface_macs.items()
        ],
        "reservation_path": str(reservation_path),
        "reloaded": reloaded,
    }


def _interface_kernel_type(
    interface: str,
    *,
    runner: Callable[..., Any],
) -> str:
    if not shutil.which("iw"):
        return "unavailable (iw not installed)"
    code, stdout, stderr = _command_output(
        ["iw", "dev", interface, "info"], runner=runner, timeout=5.0
    )
    if code:
        detail = stderr.strip() or f"exit {code}"
        return f"unavailable ({detail})"
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("type "):
            return stripped[5:].strip()
    return "unknown"


def _process_parent_pid(pid: int, proc_root: Path) -> int | None:
    try:
        raw = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
        return int(raw[raw.rindex(")") + 2 :].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def _find_airodump_processes(proc_root: Path = PROC_ROOT) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [
            value.decode("utf-8", "replace")
            for value in raw.split(b"\x00")
            if value
        ]
        if not argv or not any(Path(arg).name == "airodump-ng" for arg in argv[:2]):
            continue
        processes.append(
            {
                "pid": pid,
                "ppid": _process_parent_pid(pid, proc_root),
                "command": " ".join(argv),
            }
        )
    return sorted(processes, key=lambda item: item["pid"])


def _journal_scan_rejections(
    *,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    if not shutil.which("journalctl"):
        return {"available": False, "count": 0, "samples": []}
    code, stdout, stderr = _command_output(
        [
            "journalctl",
            "-b",
            "--no-pager",
            "--output=short-iso",
            f"--grep={_SCAN_REJECTION}",
        ],
        runner=runner,
        timeout=12.0,
    )
    if code:
        return {
            "available": False,
            "count": 0,
            "samples": [],
            "error": stderr.strip() or f"journalctl exited {code}",
        }
    lines = [
        line
        for line in stdout.splitlines()
        if ("plasmashell" in line.lower() or "plasma-nm" in line.lower())
        and _SCAN_REJECTION.lower() in line.lower()
    ]
    return {"available": True, "count": len(lines), "samples": lines[:3]}


def build_doctor_report(
    config: dict[str, Any] | None,
    active_interface: str | None = None,
    *,
    reservation_path: Path = RESERVATION_PATH,
    sysfs_root: Path = SYS_CLASS_NET,
    proc_root: Path = PROC_ROOT,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Collect read-only adapter, process, and Plasma journal diagnostics."""
    interfaces = intended_capture_interfaces(config, active_interface)
    try:
        reservation_text = reservation_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        reservation_text = ""
        reservation_error = None
    except OSError as exc:
        reservation_text = ""
        reservation_error = str(exc)
    else:
        reservation_error = None

    entries = parse_unmanaged_devices(reservation_text)
    configured_selectors = {entry.lower() for entry in entries}
    config_macs = sorted(
        {
            entry[4:].strip().lower()
            for entry in entries
            if entry.lower().startswith("mac:")
        }
    )
    interface_rows: list[dict[str, Any]] = []
    for interface in interfaces:
        try:
            mac = read_interface_mac(interface, sysfs_root=sysfs_root)
        except NetworkManagerReservationError as exc:
            mac = None
            mac_error = str(exc)
        else:
            mac_error = None

        nm_managed = "unavailable (nmcli not installed)"
        if shutil.which("nmcli"):
            code, stdout, stderr = _command_output(
                [
                    "nmcli",
                    "-f",
                    "GENERAL.NM-MANAGED",
                    "device",
                    "show",
                    interface,
                ],
                runner=runner,
            )
            value = _field_value(stdout, "GENERAL.NM-MANAGED") if code == 0 else None
            if value:
                nm_managed = value.lower()
            else:
                detail = stderr.strip() or f"exit {code}"
                nm_managed = f"unavailable ({detail})"

        interface_rows.append(
            {
                "name": interface,
                "mac": mac,
                "mac_error": mac_error,
                "in_config": bool(mac and f"mac:{mac}" in configured_selectors),
                "nm_managed": nm_managed,
                "kernel_type": _interface_kernel_type(interface, runner=runner),
            }
        )

    main = config.get("main", {}) if isinstance(config, dict) else {}
    main = main if isinstance(main, dict) else {}
    uplink = main.get("iface")
    uplink_state = "not configured"
    if isinstance(uplink, str) and uplink and shutil.which("nmcli"):
        code, stdout, stderr = _command_output(
            ["nmcli", "-f", "GENERAL.STATE", "device", "show", uplink],
            runner=runner,
        )
        value = _field_value(stdout, "GENERAL.STATE") if code == 0 else None
        if value:
            uplink_state = value
        else:
            detail = stderr.strip() or f"exit {code}"
            uplink_state = f"unavailable ({detail})"

    return {
        "reservation_path": str(reservation_path),
        "reservation_exists": reservation_path.exists(),
        "reservation_error": reservation_error,
        "config_macs": config_macs,
        "interfaces": interface_rows,
        "uplink": {"name": uplink, "state": uplink_state},
        "airodump_processes": _find_airodump_processes(proc_root),
        "journal_scan_rejections": _journal_scan_rejections(runner=runner),
    }
