"""On launch, reclaim the capture dongle from a stale instance.

Overlapping launches left several root backends and airodumps fighting over the
one monitor-mode interface; the newest could not claim it and its dashboard spun
forever. The backend now terminates any other holder of the capture interface
before claiming it, never touching its own process tree.
"""
from __future__ import annotations

import signal

from kaiagotchi.network import interface_reclaim as ir

OURS = 999  # stand-in "self"; excluded via the `exclude` set in each test

PROCS = [
    (100, ["airodump-ng", "--write", "/tmp/cap", "--output-format", "csv,pcap", "wlan3"]),
    (200, ["/home/x/venv/bin/python3", "-m", "kaiagotchi.cli", "--debug", "--port", "42681"]),
    (300, ["airodump-ng", "--write", "/tmp/other", "wlan1"]),       # different dongle
    (400, ["/usr/bin/python3", "/home/x/kaiagotchi/ui/web/hud.py"]),  # launcher, not a backend
    (999, ["/home/x/venv/bin/python3", "-m", "kaiagotchi.cli"]),     # us
]


def _lister(snapshots):
    """Return a process lister that yields each snapshot in turn, repeating the last."""
    state = {"calls": 0}

    def _list():
        i = min(state["calls"], len(snapshots) - 1)
        state["calls"] += 1
        return list(snapshots[i])
    return _list


def test_finds_airodump_on_the_interface_and_other_backends_only():
    holders = ir.find_interface_holders("wlan3", exclude={OURS}, list_processes=lambda: PROCS)
    assert set(holders) == {100, 200}  # the wlan3 airodump and the other backend
    # 300 is a different dongle, 400 is the launcher, 999 is us.


def test_our_own_tree_is_never_a_holder():
    holders = ir.find_interface_holders("wlan3", exclude={OURS, 200}, list_processes=lambda: PROCS)
    assert 200 not in holders and OURS not in holders


def test_reclaim_sigterms_then_sigkills_survivors():
    killed: list[tuple[int, int]] = []
    # Second snapshot: 200 ignored SIGTERM and still holds the interface.
    survivor = [(200, ["python3", "-m", "kaiagotchi.cli"])]
    reclaimed = ir.reclaim_capture_interface(
        "wlan3",
        list_processes=_lister([PROCS, survivor]),
        kill=lambda pid, sig: killed.append((pid, sig)),
        sleep=lambda _s: None,
        exclude={OURS},
        grace=0.0,
    )
    assert set(reclaimed) == {100, 200}
    assert (100, signal.SIGTERM) in killed and (200, signal.SIGTERM) in killed
    assert (200, signal.SIGKILL) in killed          # survived SIGTERM
    assert (100, signal.SIGKILL) not in killed      # already gone


def test_reclaim_is_a_noop_when_nobody_else_holds_it():
    killed: list[tuple[int, int]] = []
    only_us = [(OURS, ["python3", "-m", "kaiagotchi.cli"])]
    reclaimed = ir.reclaim_capture_interface(
        "wlan3",
        list_processes=lambda: only_us,
        kill=lambda pid, sig: killed.append((pid, sig)),
        sleep=lambda _s: None,
        exclude={OURS},
    )
    assert reclaimed == [] and killed == []


def test_reclaim_never_raises_on_kill_errors():
    def _boom(_pid, _sig):
        raise PermissionError("not allowed")

    reclaimed = ir.reclaim_capture_interface(
        "wlan3", list_processes=lambda: PROCS, kill=_boom, sleep=lambda _s: None, exclude={OURS},
    )
    assert set(reclaimed) == {100, 200}  # reported as attempted; errors swallowed


def test_empty_interface_name_is_a_noop():
    assert ir.reclaim_capture_interface("", list_processes=lambda: PROCS, exclude={OURS}) == []


def test_own_process_tree_walks_parents():
    # 5 -> 4 -> 1 ; the chain from 5 is {5, 4, 1}.
    parents = {5: 4, 4: 1, 1: 0}
    tree = ir.own_process_tree(pid=5, ppid_of=lambda p: parents.get(p))
    assert tree == {5, 4, 1}
