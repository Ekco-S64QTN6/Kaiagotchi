"""Reclaim the capture interface from a stale Kaiagotchi before starting.

Overlapping launches each started their own root backend and airodump, leaving
several processes fighting over the one monitor-mode dongle: the newest could
not claim it and its dashboard spun forever. On startup the (root) backend
terminates any *other* instance holding the capture interface, so only one runs
at a time. Processes in this interpreter's own tree (the backend, its sudo
wrappers, the launcher) are never signalled.
"""
from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable, Iterable

ProcessLister = Callable[[], Iterable[tuple[int, list[str]]]]

_AIRODUMP = "airodump-ng"
# A Kaiagotchi backend's capture interface comes from env/config, not argv, so
# any other backend is treated as a contender for the one dongle — this tool is
# meant to run a single instance.
_BACKEND_MARKERS = ("kaiagotchi.cli", "kaiagotchi/cli")


def _read_proc_cmdlines() -> Iterable[tuple[int, list[str]]]:
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        args = [p.decode("utf-8", "replace") for p in raw.split(b"\x00") if p]
        if args:
            yield pid, args


def _ppid(pid: int) -> int | None:
    """The parent PID from /proc/<pid>/stat, robust to spaces/parens in comm."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
        after_comm = data[data.rindex(")") + 2:].split()
        return int(after_comm[1])  # fields after comm: state, ppid, ...
    except (OSError, ValueError, IndexError):
        return None


def own_process_tree(pid: int | None = None, ppid_of: Callable[[int], int | None] = _ppid) -> set[int]:
    """This process and all of its ancestors (self, sudo wrappers, launcher)."""
    chain: set[int] = set()
    cur = os.getpid() if pid is None else pid
    for _ in range(64):
        if cur <= 0 or cur in chain:
            break
        chain.add(cur)
        parent = ppid_of(cur)
        if parent is None:
            break
        cur = parent
    return chain


def _is_holder(args: list[str], iface: str) -> bool:
    exe = os.path.basename(args[0]) if args else ""
    if _AIRODUMP in exe:
        return iface in args
    joined = " ".join(args)
    return any(marker in joined for marker in _BACKEND_MARKERS)


def find_interface_holders(
    iface: str,
    *,
    exclude: set[int],
    list_processes: ProcessLister = _read_proc_cmdlines,
) -> list[int]:
    """PIDs of airodump bound to `iface` or other backends, minus `exclude`."""
    return [
        pid
        for pid, args in list_processes()
        if pid not in exclude and _is_holder(args, iface)
    ]


def reclaim_capture_interface(
    iface: str,
    *,
    logger=None,
    list_processes: ProcessLister = _read_proc_cmdlines,
    kill: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
    exclude: set[int] | None = None,
    grace: float = 3.0,
) -> list[int]:
    """Terminate any other instance holding `iface`; return the PIDs reclaimed.

    SIGTERM first, then SIGKILL whatever still holds the interface after `grace`.
    This process's own tree is never signalled. Never raises.
    """
    if not iface:
        return []
    own = exclude if exclude is not None else own_process_tree()
    holders = find_interface_holders(iface, exclude=own, list_processes=list_processes)
    if not holders:
        return []
    if logger is not None:
        logger.warning(
            "[monitoring] capture interface %s held by stale instance(s) %s; reclaiming it",
            iface, holders,
        )

    def _signal(pids: list[int], sig: int) -> None:
        for pid in pids:
            try:
                kill(pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    _signal(holders, signal.SIGTERM)
    sleep(grace)
    survivors = find_interface_holders(iface, exclude=own, list_processes=list_processes)
    if survivors:
        _signal(survivors, signal.SIGKILL)
        sleep(0.3)
        if logger is not None:
            logger.warning("[monitoring] force-killed stale instance(s) %s on %s", survivors, iface)
    return holders
